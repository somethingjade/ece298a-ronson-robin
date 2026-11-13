
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from cocotbext.spi import SpiBus, SpiConfig, SpiMaster

IDLE = 0b000;
ABSORB = 0b001;
LFSR = 0b010;
SBOX = 0b011;
PLAYER = 0b100;

WRITE_DATA = 0b00;
WRITE_CONTROL = 0b01;
READ_DATA = 0b10;
READ_STATUS = 0b11;

def decode_status(byte):
    byte = byte & 0xFF
    error = (byte & (1 << 7)) != 0
    busy = (byte & (1 << 6)) != 0
    counter = byte & 0x3F
    return error, busy, counter

def encode_control(read_byte, pause_at, reset):
    return ((read_byte & 0xF) << 4) | ((pause_at & 0b111) << 1) | (reset & 0b1)

def generate_frame(command, data):
    return ((command & 0b11) << 14) | ((data & 0xFF) << 6)

async def read_entire_state(dut, spi_master):
    state = 0
    tx_data = []
    for i in range(11):
        tx_data.append(generate_frame(WRITE_CONTROL, encode_control(i, 0, 0)))
        tx_data.append(generate_frame(READ_DATA, 0))
    dut._log.info(f"TX: {' '.join(f'{num:04x}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:02x}' for num in rx_data)}")
    assert len(rx_data) == 22
    for i in range(11):
        error, _busy, _counter = decode_status(rx_data[2*i])
        assert error == False
        state |= (rx_data[2*i + 1] << (8 * i))
    return state
        

@cocotb.test()
async def test_project(dut):

    # Start system clock
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

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
        word_width=16,
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

    dut._log.info("")
    dut._log.info(">>> Test: Status read (ready)")
    tx_data = [generate_frame(READ_STATUS, 0x6767)]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at pLayer for next test)")
    tx_data = [generate_frame(WRITE_CONTROL, encode_control(0, PLAYER, 0))]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at pLayer for next test)")

    dut._log.info("")
    dut._log.info(">>> Test: Absorb + status read (busy) + write while busy")
    tx_data = [generate_frame(WRITE_DATA, (0x67 << 1) | 0b1), generate_frame(READ_STATUS, 0), generate_frame(WRITE_DATA, (0x99 << 1) | 0b1 << 6)]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 3
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Absorb")
    error, busy, counter = decode_status(rx_data[1])
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Status read (busy)")
    error, busy, counter = decode_status(rx_data[2])
    assert error == True
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Write while busy")
    
    dut._log.info("")
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("")
    dut._log.info(">>> Test: Least significant byte of SPONGENT-88 state")
    tx_data = [generate_frame(READ_DATA, 0x1234)]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    assert rx_data[0] == EXPECTED_STATE_LSBYTE
    dut._log.info(">>> PASSED: Least significant byte of SPONGENT-88 state")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (read msbyte for next test)")
    tx_data = [generate_frame(WRITE_CONTROL, encode_control(10, PLAYER, 0))]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (read msbyte for next test)")

    dut._log.info("")
    dut._log.info(">>> Test: Most significant byte of SPONGENT-88 state")
    tx_data = [generate_frame(READ_DATA, 0x1234)]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    assert rx_data[0] == EXPECTED_STATE_MSBYTE
    dut._log.info(">>> PASSED: Least significant byte of SPONGENT-88 state")

    dut._log.info("")
    dut._log.info(">>> Test: Entire SPONGENT-88 state")
    state = await read_entire_state(dut, spi_master)
    assert state == EXPECTED_STATE
    dut._log.info(">>> PASSED: Entire SPONGENT-88 state")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (reset)")
    tx_data = [generate_frame(WRITE_CONTROL, encode_control(0, 0, 1))]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (reset)")

    dut._log.info("")
    dut._log.info(">>> Test: State after reset")
    state = await read_entire_state(dut, spi_master)
    assert state == 0
    dut._log.info(">>> PASSED: State after reset")

    dut._log.info("")
    dut._log.info(">>> Test: Status read (ready)")
    tx_data = [generate_frame(READ_STATUS, 0x6767)]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at pLayer for next test)")
    tx_data = [generate_frame(WRITE_CONTROL, encode_control(0, PLAYER, 0))]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at pLayer for next test)")

    dut._log.info("")
    dut._log.info(">>> Test: Absorb again to make sure it didn't die after reset")
    tx_data = [generate_frame(WRITE_DATA, (0x67 << 1) | 0b1)]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    error, busy, counter = decode_status(rx_data[0])
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Absorb again")

    dut._log.info("")
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("")
    dut._log.info(">>> Test: Entire SPONGENT-88 state")
    state = await read_entire_state(dut, spi_master)
    assert state == EXPECTED_STATE
    dut._log.info(">>> PASSED: Entire SPONGENT-88 state")


    # Blocking write: waits until all words have transmitted

    # Retrieve received words

    # # Second transaction after CS_N has been idle
    # await ClockCycles(dut.clk, 5)
    #
    # tx_data = [(0x03A3) << 6]
    # dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    # await spi_master.write(tx_data)
    # rx_data = await spi_master.read()
    #
    # dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    #
    # assert len(rx_data) == 1
    # assert isinstance(rx_data, list)
    # assert rx_data[0] == ((tx_data[0] & 0x3FFF) >> 6)
    
    # # First transaction
    # tx_data = [0x0000, 0x4000, 0x8000, 0xC6B0]
    #
    # dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    #
    # # Blocking write: waits until all words have transmitted
    # await spi_master.write(tx_data)
    #
    # # Retrieve received words
    # rx_data = await spi_master.read()
    #
    # dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    #
    # assert len(rx_data) == 4
    # assert rx_data[0] == 0x0000
    # assert rx_data[1] == 0x0000
    # assert rx_data[2] == 0x00FF
    # assert rx_data[3] == ((tx_data[3] & 0x3FFF) >> 6)
    #
    # # Second transaction after CS_N has been idle
    # await ClockCycles(dut.clk, 5)
    #
    # tx_data = [(0x03A3) << 6]
    # dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    # await spi_master.write(tx_data)
    # rx_data = await spi_master.read()
    #
    # dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    #
    # assert len(rx_data) == 1
    # assert isinstance(rx_data, list)
    # assert rx_data[0] == ((tx_data[0] & 0x3FFF) >> 6)
    
    await ClockCycles(dut.clk, 20)
