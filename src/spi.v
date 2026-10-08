`default_nettype none

module spi_controller (
	input wire clk,      // clock
	input wire rst_n,     // reset_n - low to reset

	// these go to top
	input wire cs_n, // active low
	input wire mosi,
	output wire miso,
	input wire sck,

	// these go to core
	output wire rx,
	output wire sck_fall,
	input wire tx
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
	It's almost certain there exists a SPI module that allows us to set the SPI modes, meaning it should be valid to implement any SPI on our chip




	
	*/

	
	assign rx = tx;


endmodule
