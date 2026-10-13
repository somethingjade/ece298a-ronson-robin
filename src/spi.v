`default_nettype none

module spi_controller (
	input wire clk,      // device clock
	input wire rst_n,     // reset_n - low to reset

	// these go to top
	input wire cs_n, // active low
	input wire mosi,
	output wire miso,
	input wire sck, // SPI clock

	// these go to core
	output wire tx,
	output wire sck_fall,
	output wire sck_rise,
	input wire rx
);

	/*

	Wikipedia says I need shift registers to receive and output
	Recall that shift registers are a bunch of flipflops lined up that pipelines bits down to the next flipflop per clock cycle
	As SPI MOSI and MISO can only send 1 bit per clock cycle each, if we want to store values after multiple cycles, we need to use shift registers
	As such, expect that shift registers can also be reset to all 0, and also that if it is not being clocked (or set otherwise), it should keep it's values

	Also add tri-state buffers on the wires as otherwise we cannot support multiple slaves on the same bus
	
	If rst_n is pulled low, reset the state
	Is the reset state all 0? And does the state refer to the shift registers

	If cs_n is pulled high, slave should be high z
	If not, logic below is defined

	One bit is transfered per clock cycle, both ways (full duplex)
	Transmission are usually 8 bit words, but for our application we need more that 8, so maybe commonly 16?
	What should we do with the remaining bits? Perhaps use them as a CRC? But extra logic for data validity is space consuming
	If we don't choose 16, and go something more arbitrary like 10, it would be less conventional and could introduce issues for testing since master devices probably expect de-facto standards
	For example, suppose the microcontroller can only support whole-byte transmissions and sends 16 bits, but our design only takes 11 bits strictly - would our design just suddenly ignore the rest 5?
	What would happen if we are sending multiple 11bit messages padded to 16bits, would our reciever interpret the 5 padding bits as part of the next 11bit message?
	I suppose this would also require us to define, in our SPI protocol, when a message might start or ends, and other authoritative characteristics?
	In this sense, might it be better that we use a 16 bit message, and have the SPI slave expect 5 extra bits of padding and do nothing?

	MSB is usually sent first, but original SPI specs had a LSB-first enable bit

	The clock passed in might be either idle at 0, or idle at 1. In short, this determines whether you need to read on a +edge or -edge, and also changes the timing of when you send data
	There is also phase difference expected between the data bit transmission cycle to the clk
	e.g. first bit is sent immediately when cs_n is pulled low, subsequent bits are outputted when clk goes from active->idle edge, sampling on idle->active
	e.g. first bit is sent on the first edge of clk AFTER cs_n goes low, subsequent bits are outputted when clk idle->active, sampling active->idle
	Wikipedia says the conversion between the two phase options IS NOT TRIVIAL
	The above configurations are referred to as SPI modes 0 to 3. Refer to online sources for details

	In Full duplex operation, MISO and MOSI can operate in different SPI modes.
	For our application, the output and the input are mutually exclusive since serial SPONGENT requires so

	We'll have the demo board to test the actual chip - what does that microcontroller support?
	Let's assume we're using TT04+ demo board. There's a RP2040 uController, same used in Rasp Pi PICO
	The demo board can be interacted with using a website GUI, but also a python SDK that can be used with micro cocotb
	While micropython may have less access to libraries, there still exist libraries for SPI (as advised by AI)
	It's almost certain there exists a SPI module that allows us to set the SPI modes, meaning it should be valid to implement any SPI mode on our chip


	-------------------- Alternatives

	Do we need to implement shift registers to receive? While it would make the most sense from a OOP or modularization perspective, it can be considered redundant
	Suppose the shift registers stores 16 bits, with 5 padded bits. Other modules would only need to index the specific flip flop to retreive values, and output would just be assining values to the specific index, which is quite simple
	But perhaps to output, the SPONGENT ALU unit would eventually feed 8 bits into the shift register, then the SR would then feed it back into SPI.
	There is redundant feeding there - we don't necessarily need to put it into another storage space when the 88 state reg already exists.

	An idea we had is to simply remove the need of a shift register. The bits come in from MOSI, we directly feed it into CTRL and SPONGENT unit. Recall that the first stage in SPONGENT is the 88 state register
	We have to XOR the input into the state, but whether we do this all at a time or one by one doesn't matter. As such, we can just pipe out each bit one at a time and XOR it directly into the respective position
	How would differentiate between CTRL bits and input bits, and what do we do with padding bits? 
	Since we don't have that many CTRL bits, its highly feasible to turn the CTRL bits into a Finite State Machine, where depending on the FSM state (not to be confused with 88bit state), the remaining input bits will be dealt with necessarily. 
	For example, if the FSM state requires SPONGENT to ignore the rest of the message, then we don't need to process anything.
	If FSM state requires us to feed into SPONGENT, then after the first few CTRL bits are read, the remaning 8 input bits will be fed 1 by 1 into the state registers using XOR. Since we only take 8 bits, the rest of the padding bits will be ignored.
	We could track the bit count and assume that after bit 16, we expect a new message, or we could also use a specific agreement that, for example, after reading 5 zeros in a row, the next 1 indicates a new message?
	The latter option is only reasonable for messages that are a few bytes large rather a few bits large, as you could send things like device address or ID, identifiers that are not easily confused as the data portion itself
	Thus, using agreements or acknowledgements when our message is only 16 bits invites high risk of reading the 8 input bits as the beginning of a new message if the input includes smth like "000001"

	--------------------- Metastability

	We also need to consider the fact that signals are not perfectly 0 nor 1, and that flipflops may show error when reading on clock edges
	It is said that a flipflop may encounter metastability problems if the data being read changes at the same time as the flipflop samples it on a clock edge, thus violating t_setup and t_hold (time chunks within the flipflop response) run 
	This means the value in the flipflop is yet to be determined, but will stabilize after a while (under the assumption that a while is short)
	To accomdate for metastability, it might be nice to use a 2-bit shift register on both the SPI clock and MOSI. In this situation, the addition of a second register is simply to add a time delay such that the first register may stabilize at the next clock
	For example, at clock cycle 1, flipflop 1 becomes unstable, meaning the output is also unstable. This unstable output is fed to flipflop 2, but only absorbed by flipflop 2 by clock cycle 2.
	However, if we assume that 1 clock cycle is enough for flipflop 1 to stabilize, then by the time flipflop 2 reads the output of flipflop 1, the output is already stable. As such, if we were to read the output from flipflop 2, it would always be stable
	This assumption is not perfect, but may be useful in case of an actual metastability issue. This use of shift registers is considered a synchronization chain.
	If the SPI clock recieves a synchronization chain, the MOSI line must also have the same synchronization chain to ensure that the time delay for both lines are the same.
	This may be a larger problem if the chip clock is running significantly faster than the SPI clock (since the sync chain would be clocked by the chip clock, not the SPI clock)

	
	*/

	// SPI mode 0 requires the following 
	// sck is idle at 0
	// first bit is sent immediately when cs_n is pulled low, subsequent bits are outputted when clk goes from active->idle edge, sampling on idle->active
	// outputed on falling edge (immediately on select), sampled on rising

	assign tx = rx;

	reg sck_prev;
	reg sck_sync;

	reg mosi_prev;
	reg mosi_sync;

	// Defining combinational behavior
	
	assign tx = mosi_sync;
	assign sck_fall = (!sck_sync) & sck_prev;
	assign sck_rise = (!sck_prev) & sck_sync;

	// Defining sequential behavior
	always @(posedge clk) begin
		// Shift values
		sck_sync <= sck_prev;
		mosi_sync <= mosi_prev;
		sck_prev <= sck;
		mosi_prev <= mosi;

	end


endmodule
