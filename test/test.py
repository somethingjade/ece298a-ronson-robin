
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from cocotbext.spi import SpiBus, SpiConfig, SpiMaster
import SPONGENT
import logging
import random
import time

IDLE = 0b000;
ABSORB = 0b001;
LFSR = 0b010;
SBOX = 0b011;
PLAYER = 0b100;

WRITE_DATA = 0b00;
WRITE_CONTROL = 0b01;
READ_DATA = 0b10;
READ_STATUS = 0b11;

FSM_STATES = [IDLE, ABSORB, LFSR, SBOX, PLAYER]
FSM_STATES_NAMES = ["IDLE", "ABSORB", "LFSR", "SBOX", "PLAYER"]

def decode_status(byte: int):
    """
    Extracts the error, busy, and counter information from the status (8 bits or more) read in from SPI. 
    Usually used after a write command, or a read status command. Don't use this on a read data cmd, as
    data in that scenario is interpretted differently. 
    
    **Note**: Both status and data read from the device is generally 8 bits, but it can be interpretted 
    as 10 bits since the device has a feature (though not necessarily implemented) to include and report 
    what we consider *unexpected* errors in bits 9 and 10 (counting from first bit as bit 1). These errors
    occur (if implemented) when the system enters a *bad* but *possible* extraneous state, and are not related to
    host-device handshaking caught during normal operations. This feature can be *safely* ignored (probably...)
    
    Examples of unexpected errors (that are may or may not be implemented):
    - cs_n is high but spi_clock is still alive
    - internal counter becomes > 45 
    - sck_rise and sck_fall somehow manage to both exist at the same time
    - etc
    
    Args:
        byte (int): Value to be interpreted (expected to be 16 bits)
        
    Returns:
        A tuple of 5, (spi_err, spongent_err, error, busy, counter), where spi_err and spongent_err can be ignored
    """
    
    assert byte.bit_length() <= 16, "The value being interpretted is not 2 bytes?"
    byte = byte & 0x3FF
    
    spi_err = (byte & (1 << 9)) != 0
    spongent_err = (byte & (1 << 8)) != 0
    error = (byte & (1 << 7)) != 0
    busy = (byte & (1 << 6)) != 0
    counter = byte & 0x3F
    return spi_err, spongent_err, error, busy, counter

def verify_status(status: tuple, spi_err: bool, spongent_err: bool, error: bool, busy: bool, counter: int):
    assert len(status) == 5
    assert status[0] == spi_err, "spi_err"
    assert status[1] == spongent_err, "spongent_err"
    assert status[2] == error, "error"
    assert status[3] == busy, "busy"
    assert status[4] == counter, "counter"
    
    

def encode_control(read_byte: int, pause_at: int, reset: int):
    """Encode the data section of a write_ctrl message into an 8 bit message with the format and order: *read_byte*[7:4] + *pause_at*[3:1] + *reset*[0]

    Args:
        read_byte (int): an integer 4-bits wide, where if 0, it represents a squeeze operation if and only if a breakpoint is not set. 
            If from 1 to 11 inclusive, it represents which 1/11 bytes you wish to prepare the device to sample from, with no permutation immediately
            following a read_data() call. Values 1-10 map linearly to bytes [2nd - 11th] (11th is MSByte), while value 11 maps to the 1st byte (1st is LSByte)
            
        pause_at (int): an integer 3 bits-wide. the fsm_state you want to set the breakpoint to. The possible fsm_states to pause at are ABSORB, LFSR,
            SBOX, PLAYER, IDLE (setting to idle is equivalent to removing breakpoints)
        reset (int): a binary value (0 or 1) representing if you want to perform a soft reset (clear device state and other registers
            without reseting the entire board using rst_n). Note that a reset of any kind will clear breakpoints.

    Returns:
        (int): the encoded 8-bit data section for a write_ctrl message
    """
    return ((read_byte & 0xF) << 4) | ((pause_at & 0b111) << 1) | (reset & 0b1)

def generate_frame(command: int, data: int):
    """Create the full 16-bit wide message frame that will be written via SPI. The format looks like
    *command*[15:14] + *data*[13:6] + *padding*[5:0].
    
    Args:
        command (int): a 2-bit integer, either being WRITE_DATA (0), WRITE_CONTROL (1), READ_DATA (2), READ_STATUS (3)
        data (int): an 8-bit integer, which is related to the command.
            - For a write_ctrl message, use encode_control() for the data section.
            - For a write_data message, the data section is up to the user.
            - For a read_data message, the data section is not important. **Note that to use a read_data message, you must first send a write_ctrl message,**
                as the write_ctrl message contains the information of which byte to read from the 88-bit state. *This limitation of needing to send both a write_ctrl
                and read_data message to retreive a byte (instead of ONLY sending read_data) is caused by the fact that SPI requires both host and device to in/output
                in the same transaction, and that our device can only determine what command is being requested after a certain number of spi-clocks, at which point it is 
                already too late to send a full 8-bit message within that same transaction. This is also the limitation of using a 16-bit frame width.*
            - For a read_status message, the data section is not important, and can be set to anything.

    Returns:
        (int): a 16-bit wide integer, represeting a full message frame.
    """
    return ((command & 0b11) << 14) | ((data & 0xFF) << 6)

async def read_entire_state(dut: any, spi_master: SpiBus, pause_at: int):
    """Read the entire state (88 bits) at any given point, usually used after setting a breakpoint. This is implemented by reading
    each byte of the state without triggering squeeze (AKA a permutation after each read). The function will breakpoint at the
    desired fsm_state, iterate through each byte, then reset the read_byte index back to 0 before returning the total state.

    Args:
        dut (any): 
        spi_master (SpiBus):
        pause_at (int): the breakpoint location you want to read the entire state from

    Returns:
        (int): the entire 88-bit state
    """
    
    spie, spge, err, b, c = await write_control(dut, spi_master, 0, pause_at, 0)
    assert spie == False     
    assert spge == False 
    assert err == False 
    assert b == False if (pause_at == IDLE) else True
    
    state = 0
    tx_data = []
    # we can read an invalid byte (11) to read the least significant byte without starting another permutation
    tx_data.append(generate_frame(WRITE_CONTROL, encode_control(11, pause_at, 0)))
    tx_data.append(generate_frame(READ_DATA, 0))
    for i in range(10):
        tx_data.append(generate_frame(WRITE_CONTROL, encode_control(i + 1, pause_at, 0)))
        tx_data.append(generate_frame(READ_DATA, 0))
    dut._log.debug(f"TX: {' '.join(f'{num:04x}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:02x}' for num in rx_data)}")
    assert len(rx_data) == 22
    for i in range(11):
        _, _, error, _busy, _counter = decode_status(rx_data[2*i])
        assert error == False
        state |= (rx_data[2*i + 1] << (8 * i))
        
    # To reset the read_byte index, but not the breakpoint
    spie, spge, err, b, c = await write_control(dut, spi_master, 0, pause_at, 0)
    assert spie == False     
    assert spge == False 
    assert err == False 
    assert b == False if (pause_at == IDLE) else True
    
    return state

async def write_data(dut: any, spi_master: SpiBus, data: int):
    """Write a byte of data to the device that you wish to be hashed. Expect that for each byte written, if no breakpoints are set,
    a permutation should occur immediately following the message just sent from host. Message frame alignment and encodings are handled
    internally.

    Args:
        dut (any): 
        spi_master (SpiBus): 
        data (int): a byte of the total data you want to hash. Note that for a message of n-bytes (whether it includes a
            padding byte (0x8) or not), you would need to send each byte on it's own by calling this function
            each time, and you need to send it in the order:
            - byte n (MSByte)
            - byte n-1
            - byte n-2
            - ...
            - byte 2
            - byte 1 (LSByte)

    Returns:
        (tuple[spi_err, spongent_err, error, busy, counter]): the tuple represeting the status returned from MISO in the same transaction as
            the MOSI write was performed.
    """
    tx_data = [generate_frame(WRITE_DATA, data & 0xFF)]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return decode_status(rx_data[0])

async def write_control(dut: any, spi_master: SpiBus, read_byte: int, pause_at: int, reset: int):
    """Write a control message to the device. Message frame alignment and encodings are handled internally. The write_ctrl message can be
    sent even when the device is busy (during a permutation). 
    
    For example, you can set a breakpoint at SBOX while the device is still in
    permutation. Usually, the entire permutation happens much faster than the spi interface can deliver the message, so the device often receives
    the message in idle. However, in the scenario that the message does get interpreted *during* a permutation, the next round in the permutation
    may be paused at SBOX. Then you can keep changing the breakpoint to slowly increment the entire permutation.
    
    Another example is you can request a specific byte from the 88 bit state registers. You can tell the device which 1/11 bytes you wish to read
    from the 88 bit state, then call read_data() to get that byte. e.g. If you chose the 4th byte, every time you read_data() you will still get back the
    4th byte whether you set a breakpoint or not, until you change to a different byte. You can even construct the entire 88 bit state if you extract
    all 11 bytes. There are caveats, so please read below.
    
    Args:
        dut (any): _description_
        spi_master (SpiBus): _description_
        read_byte (int): an integer 4-bits wide, representing the byte you want to sample in an upcoming call to read_data().
            Take note of the following mapping:
            - 0 --> LSByte, and if no breakpoint set, trigger permutation after the read (AKA squeeze operation)
            - 11 --> LSByte
            - 1 --> 2nd LSByte
            - 2 --> 3rd LSByte
            - 3 --> 4th LSByte
            - ...
            - 9 --> 2nd MSByte
            - 10 --> MSByte
            
                    
        pause_at (int): an integer 3 bits-wide. the fsm_state you want to set the breakpoint to. The possible fsm_states to pause at are ABSORB, LFSR,
            SBOX, PLAYER, IDLE (setting to idle is equivalent to removing breakpoints)
        reset (int): a binary value (0 or 1) representing if you want to perform a soft reset (clear device state and other registers
            without reseting the entire board using rst_n). Note that a reset of any kind will clear breakpoints.
        
    Returns:
        (tuple[spi_err, spongent_err, error, busy, counter]): the tuple represeting the status returned from MISO in the same transaction as
            the MOSI write was performed.
    """
    tx_data = [generate_frame(WRITE_CONTROL, encode_control(read_byte, pause_at, reset))]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return decode_status(rx_data[0])

async def read_data(dut: any, spi_master: SpiBus, arbitrary_data=0) -> int:
    """Read a byte from the state registers. Which byte is sampled is dependent on what you set using write_control().
    If no breakpoints are set, and the read_byte set is 0, this performs a squeeze operation.
    If a breakpoint is set, or the read_byte set is in the range from 1 to 11 inclusive, get only that selected byte, with no
    permutations immediately following. Refer to ***write_control()*** for details.

    Args:
        dut (any):
        spi_master (SpiBus):
        arbitrary_data (int): can be any value as it is ignored for this command. You can also leave it default to 0.

    Returns:
        int: a 16-bit message in the format: *zero-padding*[15:10] + *spi_err*[9] + *spongent_err*[8] + *data*[7:0]
        
            spi_err and spongent_err (which can also be extracted from a status read) are always present. However, they may or may not
            not be implemented in our design, so those values might always be zero, meaning the only important information is data[7:0].
    """
    tx_data = [generate_frame(READ_DATA, arbitrary_data)]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return rx_data[0]

async def read_status(dut: any, spi_master: SpiBus, arbitrary_data=0):
    """Read the status.

    Args:
        dut (any):
        spi_master (SpiBus):
        arbitrary_data (int): can be any value as it is ignored for this command. You can also leave it default to 0.
    Returns:
        (tuple[spi_err, spongent_err, error, busy, counter]): the tuple represeting the status returned
    """
    tx_data = [generate_frame(READ_STATUS, arbitrary_data)]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return decode_status(rx_data[0])

async def wait_for_ready(dut: any, spi_master: SpiBus):
    """Continuously read the status of the device until it is no longer busy, and an error has not occured.
    Busy represents any time the device is in a permutation, i.e. absorb, lfsr, sbox, player. Error
    represents if the host tried to write data to the device while it was performing a permutaiton. This
    error is considered an *expected* error.

    Args:
        dut (Any): 
        spi_master (SpiBus): 

    Returns:
        (bool): Whether an *expected* error was detected while waiting for the status 
    """
    _, _, error, busy, _ = await read_status(dut, spi_master)
    while busy and not error:
        _, _, error, busy, _ = await read_status(dut, spi_master)
    return not error

async def hash(dut: any, spi_master: SpiBus, msg: int, num_bytes: int):
    """    
    **If you set a breakpoint or you used write_ctrl to set a specific read_byte, the behavior or outcome
    of this specific hash call may not work as intended, and can yield in a deadlock.**
        
    Performs a full hash operation, **given that you set up the system properly before calling this**.
    Note the following expected behavior:
    1 Absorption per hash, 1 grouping of (LFSR >> sBox >> pLayer) per round,
    45 rounds per permutaiton, 1 permutation per byte of message (including 0x8 padding),
    1 permutation per 8/88 bits read back from state registers.
    
    Args:
        dut (any): 
        spi_master (SpiBus): The SpiBus containing the 4 signals required for transactions
        msg (int): a byte-aligned value of otherwise arbitrary length that the user plans to get hashed.
            Byte alignment is requied due to the limitations of our spongent implementation.
            e.g. actual message: 0110 --> byte-aligned: 00000110
            
            Pre-processing such as bit shifting, masking control bits, write/read operatoins, are performed internally.
        num_bytes (int): How many bytes the message is

    Returns:
        (int): The final hash output. This is always going to be at most 88 bits.
    """
    ret = 0
    msg = (msg << 8) | 0x80 # padding performed on the basis that everything is byte aligned
    for i in reversed(range(num_bytes + 1)):
        byte = (msg >> (i*8)) & 0xFF
        await wait_for_ready(dut, spi_master)
        await write_data(dut, spi_master, byte)
    for _ in range(0, 11):
        await wait_for_ready(dut, spi_master)
        ret <<= 8
        ret |= await read_data(dut, spi_master)
    await wait_for_ready(dut, spi_master)
    return ret

def load_expected_values(dut: any, message_block: int):
    """Using the python implementation of SPONGENT, create a spongent object and perform a single round
    (absorb, lfsr, sbox, player) on a 1-byte input message, and track the state registers at the end
    of each fsm_state/operation.

    Args:
        dut (any):
        message_block (int): a byte-wide input message

    Returns:
        tuple[ list[absorb_state, lfsr_state, sbox_state, player_state], spongent ]:
            a list containing the expected value of the state registers at each fsm_state in only one round,
            as well as the spongent object
    """
      
    # Create the Spongent-88 instance
    spongent = SPONGENT.SPONGENT(n=88, c=80, r=8, R=45)
    # Initial 88-bit state (all zeros)
    state = 0
    message_block = message_block & 0xFF
    
    # 1. Absorb: XOR message into LSB 8 bits
    state ^= message_block 
    absorb_state = state
    # 2. Generate and apply round constants
    tmp = spongent.LFSR
    revLFSR = 0

    for _ in range(spongent.LFSRsize):
        revLFSR = (revLFSR << 1) | (tmp & 0x1)
        tmp >>= 1

    state ^= revLFSR << (spongent.r + spongent.c - spongent.LFSRsize)
    state ^= spongent.LFSR
    lsfr_state = state
    
    # 3. Advance LFSR
    spongent.lCounter()
    
    # 4. Apply S-box layer
    state = spongent.sBoxLayer(state)
    sbox_state = state
    dut._log.info(f"FULL: {state:022X}")
    dut._log.info(f"LSB: {bin(state & 0xFF)}")
    
    # 5. Apply pLayer
    state = spongent.pLayer(state)
    player_state = state
    dut._log.info(f"FULL: {state:022X}")
    dut._log.info(f"LSB: {bin(state & 0xFF)}")
    
    # Final 88-bit state after one round
    return [absorb_state, lsfr_state, sbox_state, player_state], spongent

def apply_next_round(spongent: SPONGENT.SPONGENT, previous_states: list):
    """Apply the next round of a permutation to a list of previous states and update that list. While the list
    contains absorb_state, lfsr_state, sbox_state, player_state, only the player_state is used to compute
    the next lfsr, sbox, and player states. Absorb_state stays the same, granted it only occurs once per
    permutation.

    Args:
        spongent (SPONGENT.SPONGENT): the spongent object used to load the initial values of the states
        previous_states (list): a list containing [absorb_state, lfsr_state, sbox_state, player_state]

    Returns:
        list[absorb_state, lfsr_state, sbox_state, player_state]: an updated list of the state registers at each fsm_state
    """
    state = previous_states[-1]

    tmp = spongent.LFSR
    rev_lfsr = 0
    for _ in range(spongent.LFSRsize):
        rev_lfsr = (rev_lfsr << 1) | (tmp & 1)
        tmp >>= 1

    state ^= rev_lfsr << (spongent.r + spongent.c - spongent.LFSRsize)
    state ^= spongent.LFSR
    lfsr_state = state

    spongent.lCounter()
    state = spongent.sBoxLayer(state)
    sbox_state = state
    state = spongent.pLayer(state)

    return [previous_states[0], lfsr_state, sbox_state, state]


        

@cocotb.test()
async def test_project(dut):

    # Start system clock
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut._log.setLevel(logging.INFO)

    # Reset DUT
    dut._log.info("Reset")

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0

    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1

    # Initialize SPI bus
    spi_bus = SpiBus.from_prefix(dut, prefix="spi", cs_name="cs")

    spi_config = SpiConfig(
        sclk_freq=10000000,
        word_width=16, # Must be 16 per our implementation limitations
        cpol=False,
        cpha=True,
        msb_first=True,
        cs_active_low=True
    )

    spi_master = SpiMaster(spi_bus, spi_config)
    
    # Allow CS_N to settle after reset
    await ClockCycles(dut.clk, 5)

    EXPECTED_STATE_LSBYTE = 0x98 # from existing implementation
    EXPECTED_STATE_MSBYTE = 0x8e # from existing implementation
    EXPECTED_STATE = 0x8eeeeeeeeeeeeeeeeeee98 # from existing implementation
    EXPECTED_STATE_END = 0xe95aa77a862489d1e04491 # from existing implementation

    TEST_VECTOR = 0x53706F6E6765202B2050726573656E74203D2053706F6E67656E74
    EXPECTED_HASH = 0x69971BF96DEF95BFC46822



    # ========================================= BASIC TESTS =========================================
    dut._log.info("\n>>> Test: Status read (ready)")
    status = await read_status(dut, spi_master)
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("\n>>> Test: Control write (breakpoint at absorb)")
    status = await write_control(dut, spi_master, 0, ABSORB, 0)
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: Control write (breakpoint at absorb)")

    dut._log.info("\n>>> Test: Entire state after init")
    state = await read_entire_state(dut, spi_master, ABSORB)
    assert state == 0
    dut._log.info(">>> PASSED: Entire state after init")

    dut._log.info("\n>>> Test: Absorb + status read (busy) + write while busy")
    status = await write_data(dut, spi_master, (0x67 << 1) | 0b1)
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: Absorb")
    status = await read_status(dut, spi_master)
    verify_status(status, False, False, False, True, 0)
    dut._log.info(">>> PASSED: Status read (busy)")
    status = await write_data(dut, spi_master, (0x99 << 1) | 0b1 << 6)
    verify_status(status, False, False, True, True, 0)
    dut._log.info(">>> PASSED: Write while busy")
    
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("\n>>> Test: Control write (breakpoint at lfsr)")
    status = await write_control(dut, spi_master, 0, LFSR, 0)
    verify_status(status, False, False, False, True, 0)
    dut._log.info(">>> PASSED: Control write (breakpoint at lfsr)")

    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("\n>>> Test: Control write (breakpoint at sbox)")
    status = await write_control(dut, spi_master, 0, SBOX, 0)
    verify_status(status, False, False, False, True, 0)
    dut._log.info(">>> PASSED: Control write (breakpoint at sbox)")

    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("\n>>> Test: Control write (breakpoint at player)")
    status = await write_control(dut, spi_master, 0, PLAYER, 0)
    verify_status(status, False, False, False, True, 0)
    dut._log.info(">>> PASSED: Control write (breakpoint at player)")

    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("\n>>> Test: Control write (breakpoint at absorb)")
    status = await write_control(dut, spi_master, 0, ABSORB, 0)
    verify_status(status, False, False, False, True, 0)
    dut._log.info(">>> PASSED: Control write (breakpoint at absorb)")
    
    await ClockCycles(dut.clk, 960) # wait for a full permutation

    dut._log.info("\n>>> Test: Control write (breakpoint at idle)")
    status = await write_control(dut, spi_master, 0, IDLE, 0)
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: Control write (breakpoint at idle)")

    dut._log.info("Waiting for ready")
    await wait_for_ready(dut, spi_master)

    dut._log.info("\n>>> Test: Status read (ready)")
    status = await read_status(dut, spi_master)
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("\n>>> Test: Entire state")
    state = await read_entire_state(dut, spi_master, IDLE)
    assert state == EXPECTED_STATE_END
    dut._log.info(">>> PASSED: Entire state")

    # We need to test this feature more, especially after a permutation or round
    dut._log.info("\n>>> Test: Control write (reset)")
    status = await write_control(dut, spi_master, 0, IDLE, 1)
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: Control write (reset)")
    

    # DO NOT REMOVE THIS COMMENT
    # TODO: One of the test cases for testing spi should be mass write
    # right now, we use the helper function write_control and write_data, but they only perform
    # one byte write at a time, instead of writing all bytes in a single transaction
    # i.e. tx_data = [0x00, 0x01, 0x02, 0x03, ..., n_th byte]
    # read back n+1 bytes in a single transaction
    # This is important because the behavior of the cs_n signal may or may not be different on 
    # actual HW vs the simulation
    
    await ClockCycles(dut.clk, 20)
    
    
    

    
    # ========================================= COMPONENT FUNCTIONAL TESTING =========================================
    dut._log.info("---------------- CHECKING WITH PYTHON IMPLEMENTATION ----------------")    
    
    component_states, spongent = load_expected_values(dut, message_block=(0x67 << 1) | 0b1)
    # component_states will be a list of size 4, [absorb, lfsr, sbox, player]
    
    
    # the function is defined here because it is not a helper function, and rather part of the test plan itself
    async def component_tests(dut, spi_master: SpiBus, message_block: int, component_states: list[int], reset_per_component: bool, permutation: bool):
        """
        A function that tests the system's breakpoint capabilities for the main internal spongent components: absorb, lfsr, sbox, player.
        In a single round, all 4 fsm_states will be paused at, read from, and compared to the expected values given from the Spongent implementation
        in python.
        Args:
            dut: 
            spi_master: the SpiBus being used for this dut
            message_block: an 8-bit message, with or without padding doesn't matter
            component_states: a list[int] of size 4 containing the the entire 88-bits of each fsm_state: absorb, lfsr, sbox, player
            reset_per_component: set to True if you want to reset the device for each possible breakpoint that can be tested. 
                            For example, the device will be reset when the breakpoint is set to lfsr, and when the breakpoint changes to sbox, the device 
                            will be reset again. Naturally, this requires us to re-absorb the message before we reach the sbox state. Setting this parameter
                            to True will only allow 1 round to run out of the 45 rounds per permutation.
            permutation: set this to True if you want all 45 rounds in the permutation to run. This means that for a single 8-bit data absorbed, 
                        45 rounds of lfsr->sbox->player will be performed. This is tested and implemented using the existing python implementation. 
        Returns:
            A tuple of 3, (error, busy, counter)
        """
        dut._log.info("\n\nReset\n\n")
        dut.ena.value = 1
        dut.ui_in.value = 0
        dut.uio_in.value = 0
        dut.rst_n.value = 0

        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 10)
                
        # When performing 45 rounds, we do not want to reset at each breakpoint
        reset_per_component = False if permutation else reset_per_component
        first_time_absorbing = True
        
        for cnt in range(45 if permutation else 1): # cnt is the counter tracking 45 rounds of permutation in the python implementation
            if (permutation):
                dut._log.info(f"\n>>> Test: Performing Round {cnt}")
            
            # For each possible fsm_state that can be paused
            for i in range(4): 
                if (cnt > 0 and i == 0):
                    # If not on the very first round, ignore the ABSORB STATE
                    continue
                
                if (reset_per_component):
                    dut._log.info("\n\nReset\n\n")
                    dut.ena.value = 1
                    dut.ui_in.value = 0
                    dut.uio_in.value = 0
                    dut.rst_n.value = 0

                    await ClockCycles(dut.clk, 5)
                    dut.rst_n.value = 1
                    await ClockCycles(dut.clk, 10)
                    
                # First step, set the break point at the correct location
                if (not permutation):
                    dut._log.info(f"\n----- SET BREAKPOINT AT {FSM_STATES_NAMES[i+1]} -----")
                    dut._log.info(">>> Test: Control write")
                status = await write_control(dut, spi_master, 0, FSM_STATES[i+1], 0)
                assert status[0] == False
                assert status[1] == False
                assert status[2] == False
                assert status[3] == False if reset_per_component else True
                if (cnt == 0):
                    assert status[4] == cnt 
                    # Note that when we change the breakpoint, the fsm_state and the counter do not change immediately.
                    # They change on the next clock cycle, but not fast enough to make it on the current miso output.
                    # As such, the fsm_state and the counter read from this write command would still be old values.
                    # However, this isn't a problem on the first round as the counter is already 0 anyways.
                    # As such, we need a seperate read/write command after we wait for one extra clock cycle.
                if (not permutation):
                    dut._log.info(f">>> PASSED: Control write for setting bp to {FSM_STATES_NAMES[i+1]}")
                
                await ClockCycles(dut.clk, 1)                
                
                # Second step, absorb a byte of data into the state registers once. Only permit re-absorbing at each breakpoint if you reset everything
                if (reset_per_component or first_time_absorbing):
                    dut._log.info(f"\n>>> Test: Absorb + status read (busy)")
                    status = await write_data(dut, spi_master, message_block)
                    verify_status(status, False, False, False, False, cnt)
                    dut._log.info(">>> PASSED: Absorb")
                    status = await read_status(dut, spi_master)
                    verify_status(status, False, False, False, True, cnt)
                    dut._log.info(">>> PASSED: Status read (busy)")
                    first_time_absorbing = False
                    
                    dut._log.info(f"\n>>> Test: Full state after absorb")
                    state = await read_entire_state(dut, spi_master, FSM_STATES[i+1])
                    assert state == component_states[i]
                    dut._log.info(f">>> PASSED: Full state after absorb")

                
                # Third step, try writing while the system is busy
                if (not permutation):
                    dut._log.info(f"\n>>> Test: Write while busy at {FSM_STATES_NAMES[i+1]}")
                status = await write_data(dut, spi_master, (0x99 << 1) | (1 << 6))
                verify_status(status, False, False, True, True, cnt)
                if (not permutation):
                    dut._log.info(f">>> PASSED: Write while busy at {FSM_STATES_NAMES[i+1]}")
                
                # Fourth step, read the entire state registers for this specific breakpoint (fsm_state)
                if (not permutation):
                    dut._log.info(f"\n>>> Test: SPONGENT-88 state at {FSM_STATES_NAMES[i+1]}")
                state = await read_entire_state(dut, spi_master, FSM_STATES[i+1])
                assert state == component_states[i]
                if (not permutation):
                    dut._log.info(f">>> PASSED: SPONGENT-88 state at {FSM_STATES_NAMES[i+1]} matches python implementation")
                
                # Fifth step, read the LSByte from the state registers AGAIN to ensure state is not changing without any mosi input
                # Note that a permutation will not happen since the breakpoint is not set to IDLE
                await ClockCycles(dut.clk, 10)
                if (not permutation):
                    dut._log.info(f"\n>>> Test: LSByte again after 10clck delay at {FSM_STATES_NAMES[i+1]}")
                rx_data = await read_data(dut, spi_master)
                assert rx_data == (component_states[i] & 0xFF)
                if (not permutation):
                    dut._log.info(f">>> PASSED: Least significant byte of SPONGENT-88 state at {FSM_STATES_NAMES[i+1]}")
                await ClockCycles(dut.clk, 10)
                    
            if (permutation):
                dut._log.debug("\nApplying next round to python implementation")
                dut._log.debug(f"Before: {component_states}")
                component_states = apply_next_round(spongent, component_states)
                dut._log.debug(f"After: {component_states}")
                dut._log.info(f">>> PASSED: Round {cnt}")
                    
                    
    dut._log.info(f"\n---------------- RESET AT EACH BREAKPOINT, 1 ROUND ----------------")        
    time.sleep(3) 
    await component_tests(dut, spi_master, (0x67 << 1) | 0b1, component_states, reset_per_component=True, permutation=False)
    dut._log.info(f"\n---------------- RESET ONCE, TRAVERSE EACH BREAKPOINT, 1 ROUND ----------------") 
    time.sleep(3) 
    await component_tests(dut, spi_master, (0x67 << 1) | 0b1, component_states, reset_per_component=False, permutation=False)
    dut._log.info(f"\n---------------- PERMUTATION: 45 ROUNDS, EACH WITH BREAKPOINTS, WITH PRE-SET INPUT ----------------") 
    time.sleep(3) 
    timeout = time.perf_counter()
    await component_tests(dut, spi_master, (0x67 << 1) | 0b1, component_states, reset_per_component=False, permutation=True)
    timeout = time.perf_counter() - timeout
    if (timeout < 30):
        dut._log.warning("TIMEOUT ON PERMUTATION")
    # Try the full permutation with a randomly generated byte
    dut._log.info(f"\n---------------- PERMUTATION: 45 ROUNDS, EACH WITH BREAKPOINTS, WITH RANDOM INPUT BYTE ----------------") 
    time.sleep(3) 
    custom_random_byte = random.randint(0, 255)
    component_states, spongent = load_expected_values(dut, message_block=custom_random_byte)
    timeout = time.perf_counter()
    await component_tests(dut, spi_master, custom_random_byte, component_states, reset_per_component=False, permutation=True)
    timeout = time.perf_counter() - timeout
    if (timeout < 30):
        dut._log.warning("TIMEOUT ON PERMUTATION")
    dut._log.info(f"\nThe behavior for each component is as expected, and the system behavior is expected for a single permutation")
    
    dut._log.info(f"")
     
    
    
    # ========================================= SYSTEM FUNCTIONAL AND BEHAVIOR TESTS =========================================
    dut._log.info("\n\nReset\n\n")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)
                        
    dut._log.info("\n---------------- TESTING A FULL HASH VECTOR ----------------")
    time.sleep(3)                    
    dut._log.info("\n>>> Test: Test a full hash vector after hard reset")
    timeout = time.perf_counter()
    hash_result = await hash(dut, spi_master, TEST_VECTOR, int(216/8))
    timeout = time.perf_counter() - timeout
    if (timeout < 10):
            dut._log.warning("TIMEOUT ON PERMUTATION")
    assert hash_result == EXPECTED_HASH
    dut._log.info(">>> PASSED: hash test vector (hard reset)")
    
    dut._log.info("\n---------------- CHECKING STATE BEFORE AND AFTER RESETTING PREVIOUS STATE ----------------")
    time.sleep(3) 
    dut._log.info("\n>>> Test: Test a full hash vector without resetting (corrupted state)")
    hash_result = await hash(dut, spi_master, TEST_VECTOR, int(216/8))
    assert hash_result != EXPECTED_HASH
    dut._log.info(">>> PASSED: corrupt state hash test vector")
    
    dut._log.info("\n>>> Test: Soft reset clears states")
    status = await write_control(dut, spi_master, 0, IDLE, 1)
    verify_status(status, False, False, False, False, 0)
    
    # read all state
    state = await read_entire_state(dut, spi_master, IDLE)
    assert state == 0
        
    rx_data = await read_data(dut, spi_master)
    assert rx_data == 0x0 # ensure that at least the LSByte of the state is 0
    # begin permutation
        
    await wait_for_ready(dut, spi_master)
    state = await read_entire_state(dut, spi_master, IDLE)
    dut._log.debug(f"State after squeeze: 0x{state:x}")
    assert state == 0x7CC08139EB7F16CFCEF382 # This can be proven using component_tests(), the python implementation
    assert state.bit_length() <= 88 # for some reason, needs to be -2 because the prefix "0b" is included in bin()
    dut._log.info(">>> PASSED: State is cleared, and squeeze causes permutation")
    
    status = await write_control(dut, spi_master, 0, IDLE, 1)
    verify_status(status, False, False, False, False, 0)
        
    hash_result = await hash(dut, spi_master, TEST_VECTOR, int(216/8))
    assert hash_result == EXPECTED_HASH
    dut._log.info(">>> PASSED: Full hash after a soft reset")
    
    dut._log.info("\n---------------- TESTING A RANDOM SIZE RANDOM VALUE HASH VECTOR ----------------")
    time.sleep(3)
    for i in range(10):
        dut._log.info(f"\n>>> Test: Random hash vector {i}")
        status = await write_control(dut, spi_master, 0, IDLE, 1)
        verify_status(status, False, False, False, False, 0)
        dut._log.debug(f"Soft Reset Successful")
        
        random_byte_aligned_size = random.randint(1, 11) # I chose 11 arbitrarily
        random_message = (1 << (8*random_byte_aligned_size)) - 1 # turn something like 0x100 to 0x0FF
        random_message = random.randint(0, random_message)
        dut._log.info(f"Random message: 0x{random_message:x} of size: {random_byte_aligned_size}")
        
        expected_result = spongent.hash(random_message, random_byte_aligned_size*8 - random_message.bit_length())
        dut._log.debug(f"Python implementation hash output: 0x{expected_result:x}")
        hash_result = await hash(dut, spi_master, random_message, random_byte_aligned_size)
        dut._log.debug(f"Device hash output: 0x{hash_result:x}")
        
        assert expected_result == hash_result, "FAIL"
        dut._log.info(f">>> PASSED: Random hash vector {i}")

    
    # ========================================= NEGATIVE TESTING =========================================
    # I wanna try using a read_data command to try to set a write_ctrl command, not sure if thats possible
    # Also considering that I was writing the doc string comments for these functions, I have discovered
    # some possible tests to check unwarranted behavior, especially when using write_ctrl()
    # the full hash function doesn't set a breakpoint, nor does it use write_ctrl to set read_byte to 0,
    # so it is possible to get a corrupt hash out! We need to test this, but this is a buggy implementation from
    # the testing interface, and not of our verilog design
    
    dut._log.info("\n\nReset\n\n")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)
    
    dut._log.info("\n---------------- NEGATIVE TESTING ----------------")
    time.sleep(3)
    # Setting a breakpoint that doesn't exist
    dut._log.info("\n>>> Test: Set a fake breakpoint and check if squeeze is blocked")
    for j in range(4, 8):    
        status = await write_control(dut, spi_master, 0, j, 0)
        verify_status(status, False, False, False, False, 0)    
        # Expected behavior is that none of the fsm_states are paused, but squeeze is also blocked
        state = await read_entire_state(dut, spi_master, j)
        assert state == 0
        
        for i in range(5):
            await wait_for_ready(dut, spi_master)
            rx_data = await read_data(dut, spi_master)
            assert rx_data == 0x0, f"Squeeze was not blocked at iteration {i}"
        
        state = await read_entire_state(dut, spi_master, IDLE)
        assert state == 0
    dut._log.info(">>> PASSED: State remains unchanged after squeeze")  
    
    dut._log.info("\n>>> Test: Set a fake breakpoint on a non-zero state and check if squeeze returns 0")
    status = await write_control(dut, spi_master, 0, IDLE, 0)
    verify_status(status, False, False, False, False, 0)
    await wait_for_ready(dut, spi_master)
    rx_data = await read_data(dut, spi_master)
    assert rx_data == 0x0
    await wait_for_ready(dut, spi_master)
    
    for j in range(4, 8):    
        status = await write_control(dut, spi_master, 0, j, 0)
        verify_status(status, False, False, False, False, 0)    
        # Expected behavior is that none of the fsm_states are paused, but squeeze is also blocked
        state = await read_entire_state(dut, spi_master, j)
        assert state == 0
        
        for i in range(5):
            await wait_for_ready(dut, spi_master)
            rx_data = await read_data(dut, spi_master)
            assert rx_data == 0x0, f"Squeeze was not blocked at iteration {i}"
        
        state = await read_entire_state(dut, spi_master, IDLE)
        assert state == 0x7CC08139EB7F16CFCEF382
    dut._log.info(">>> PASSED: No squeeze operations happened")
    
    status = await write_control(dut, spi_master, 0, IDLE, 1)
    verify_status(status, False, False, False, False, 0)
    
    dut._log.info("\n>>> Test: Try writing control messages without using write_ctrl")
    await wait_for_ready(dut, spi_master)
    rx_data = await read_data(dut, spi_master, encode_control(11, IDLE, 0))
    assert rx_data == 0
    # Expect that squeeze operation will happen
    
    await wait_for_ready(dut, spi_master)
    rx_data = await read_data(dut, spi_master, encode_control(0, IDLE, 0))
    assert rx_data == 0x82 # from 0x7CC08139EB7F16CFCEF382
    # Expect permutation
    
    
    
    # DELETE THE LINE BELOW
    # component_states, spongent = load_expected_values(dut, message_block=(0x67 << 1) | 0b1)
    s = spongent.P(0x7CC08139EB7F16CFCEF382)
    
    await wait_for_ready(dut, spi_master)
    rx_data = await read_data(dut, spi_master, encode_control(0, PLAYER, 0))
    dut._log.debug(f"rx_data: 0x{rx_data:x}")
    assert rx_data == s & 0xFF
    # Permutation
    
    s = spongent.P(s)
    await wait_for_ready(dut, spi_master) # should not soft lock
    rx_data = await read_data(dut, spi_master, encode_control(11, IDLE, 1))
    assert rx_data == s & 0xFF
    # Expect No soft reset
    
    s = spongent.P(s)
    await wait_for_ready(dut, spi_master)
    rx_data = await read_data(dut, spi_master, encode_control(0, PLAYER, 0))
    assert rx_data == s & 0xFF
    dut._log.info(">>> PASSED: read_data() did not trigger write_ctrl behaviors")
    
    # Soft Reset
    await wait_for_ready(dut, spi_master)
    status = await write_control(dut, spi_master, 0, IDLE, 1)
    verify_status(status, False, False, False, False, 0)
    
    status = await read_status(dut, spi_master, encode_control(11, IDLE, 0))
    verify_status(status, False, False, False, False, 0)

    rx_data = await read_data(dut, spi_master)
    assert rx_data == 0
    
    await wait_for_ready(dut, spi_master)
    rx_data = await read_data(dut, spi_master)
    assert rx_data == 0x82
    
    # The status read should happen during the permutation, so should be busy
    status = await read_status(dut, spi_master, encode_control(11, PLAYER, 0))
    assert status[0] == False
    assert status[1] == False
    assert status[2] == False # error
    assert status[3] == True # busy
    assert status[4] >= 0 # counter
    
    await wait_for_ready(dut, spi_master) # should not soft lock
    status = await read_status(dut, spi_master, encode_control(11, PLAYER, 0))
    verify_status(status, False, False, False, False, 0)
    dut._log.info(">>> PASSED: read_status() did not trigger write_ctrl behaviors")
    
    dut._log.info("\n>>> Test: Set a read_byte index larger than 11")
    status = await write_control(dut, spi_master, 0, IDLE, 1)
    verify_status(status, False, False, False, False, 0)
    rx_data = await read_data(dut, spi_master)
    assert rx_data == 0
    # Permutation
    await wait_for_ready(dut, spi_master)
    for i in range (11, 16):
        status = await write_control(dut, spi_master, i, IDLE, 0)
        verify_status(status, False, False, False, False, 0)
        rx_data = await read_data(dut, spi_master)
        assert rx_data == 0x82  
    
    dut._log.info(">>> PASSED: Equivalent to setting to index 11")