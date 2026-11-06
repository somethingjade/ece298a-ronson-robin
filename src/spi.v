`default_nettype none

module spi_controller (
	input wire clk,      // device clock
	input wire rst_n,     // reset_n - low to reset

	// these go to top
	input wire cs_n, // active low
	input wire mosi,
	output wire miso,
	input wire sck, // SPI clock
	input start_write, // start the output

	// these go to core
	output wire tx,
	output wire sck_fall,
	output wire sck_rise,
	input wire rx,
	input wire error_status
);

	/*

	--------------------- Design Considerations

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

	--------------------- Other

	Let's consider using SPI mode 0, meaning sck is considered idle when at a logic low, the first bit is outputed immediately when cs_N is pulled low, then every subsequent bits are outputed on
	the falling edge of the clock, and sampled on the rising edge of the clock. There is a non-arbitrary time delay between when cs_n is pulled low and the first falling edge of the clock. As such,
	our system needs output on both cs_n and the falling edge of the clock, while also keeping track of which bit to send. 
	
	It would simpler to only track the clock edge to output bits, and just have cs_n be a condition that needs to be fulfilled combinationally.
	It would make more sense for us to consider SPI mode 1, which is output on rising edge of clock only, sample on falling edge, both of which only happen after cs_n has pulled low.
	The first bit outputed happens on the first rising edge of the clock. Clock is still considered idle at a logic low.

	
	*/


	assign miso = shift_registers[5]; // rx from external module

	reg sck_next;
	reg sck_sync;

	reg mosi_next;
	reg mosi_sync;
	reg error_mask[1:0]; // This register is used to mask the output if an error has appeared in either the spi module or the spongent core
	reg shift_registers[5:0];
	reg output_enable;

	// Defining combinational behavior
	
	assign tx = mosi_sync;
	assign sck_rise = (!sck_sync) & sck_next;
	assign sck_fall = (!sck_next) & sck_sync;

	// Defining sequential behavior

	always @(posedge clk or negedge rst_n or negedge cs_n) begin
		error_mask[1] <= error_status;
		output_enable <= start_write; // y
		

		if (!rst_n) begin
			// I can foresee issues with this implementation. What if during reboot, clock is actually
			// high, then you would get a rising edge (since registers are set to 0 initially) immediately since sck_next reads in sck
			// But also note that the specs for SPI mode 1 indicate clock is idle at a voltage low, so this scenario should never happen.
			// However, supposing that the possiblity is there, I can't design an error handler for it since it requires that you check the 
			// the value of sck (and not the sck_next and sck_sync registerss) immediately following cs_n pulling low, and that requires using
			// a register to keep track of the boolean status that this is the first time you're checking sck (as not using a boolean variable)
			// forces the system to check sck every internal clk cycle, thus failing all valid values
			sck_next <= 0; // in SPI mode 1, the clock is idle when low
			sck_sync <= 0;
			mosi_next <= 0;
			mosi_sync <= 0;
			error_mask[1:0] <= 2'b0;
			output_enable = 0;
			shift_registers[5:0] <= 6'b0;
		end else begin // If in normal operation
			if (!cs_n) begin // MOSI only read if chip select low
				// Conceptually, we sample on the falling edge of sck, but tx is assigned to mosi_sync, and mosi_sync
				// is always being updated every interal clock cycle. Thus, as long as sck_fall is true, any external module
				// can sample the current tx and get the value at the right time instance, rather than the SPI module
				// managing the internal timing and bit storage using a shift register. While not considered OOP design, this reduces complexity of other modules
				// handling data transfer to and from the SPI module's shift register. As such, SPI just becomes an interface with no shift register of its own
				

				// SPI clock only starts after cs_n, this part always runs
				// Consider, what if cs_n pulls high? The values of _next and _sync freeze, which
				// could potentially make sck_rise or sck_fall always true, forcing external modules dependent on these signals to keep being activated
				// However, such a scenario should never happen as sck is supposed to remain idle for a period of time before cs_n pulls up (i.e after the last rising edge 
				// that sends the final data bit, it falls and remains a logic low all while cs_n is still pulled low).
				// While mosi_next and mosi_sync is non-deterministic after cs_n, sck_next and sck_sync should be in a known state (low).
				// Else, we should consider this a bug in the system, or from the host side. Instead of resetting all the registers to 0 when cs_n is high,
				// I'd rather have them take on a value that represents an error ????
				sck_sync <= sck_next;
				sck_next <= sck;
				
				mosi_sync <= mosi_next;
				mosi_next <= mosi;

				// Regarding output, is SPI module responsible for managing the timing and data sent to the host?
				// i.e. let's assume that host and device are both writing and reading at the same time, meaning device follows SPI mode 1 after cs_N
				// However, our device can't provide data immediately as we need to know the control bits (and thus the finite state macine) first, so 
				// only a part of the returning output is actually valid to read by the host. Which bits should those be? Is the size of data being set


				// OUTPUT DESIGN
				// According to the design of the spongent module, it samples from the spi module on a rising edge, and outputs on a falling edge
				// Granted, the first two MSB of data received from the host represents control bits and thus 1/4 of the possible states in the FSM 
				// the system can take on. As such, when the system reads the ctrl bits and realizes it needs to send data back to host, it will send 
				// the first bit of data immediately on the third sck rising edge (based on testing, the system is ready for output immediately after
				// reading the second ctrl bit). Consider the exapmle below
				// INPUT:  1000 0000 01-- ---- (ctrl: 10, data: 0000 0001, padding: -- ----)
				// OUTPUT: --00 1010 11-- ---- (data: 0010 1011, all "-" are considered padding)
				// The issue above is that the host may only be able to receive data in bytes, meaning while the device meant to send 0010 1011, the host will
				// receive --00 1010, 11-- ---- as two seperate bytes, and then the host would need to perform some kind of byte-alignment translation (bit shifting)

				// It would be better if we differentiated the first byte as something like a crc, or error status, and the second byte to be just data.
				// To do this, we'll shift the actual data by 6 sck cycles using a shift register
				if (output_enable) begin
					if (sck_rise) begin
						shift_registers[5] <= shift_registers[4];
						shift_registers[4] <= shift_registers[3];
						shift_registers[3] <= shift_registers[2];
						shift_registers[2] <= shift_registers[1];
						shift_registers[1] <= shift_registers[0];
						shift_registers[0] <= rx;
					end
				end

			end else begin
				if (sck_next | sck_sync) begin // if either values is 1, then the system has entered a bad state
					error_mask[0] <= 1;
				end
				shift_registers[5:2] <= 4'b0; // clear shift register
				shift_registers[0] <= error_mask[0];
				shift_registers[1] <= error_mask[1];
			end
		end
	end

	/*
	-------------- Questions --------------
	Who is keeping track of 16 total bits?
		If I assume the spongent core deals with the bits, then it would be that 10 bits enter, the 2 MSB act as control for write data, write control, read data, read status, and then the next 8 are XOR'ed into status reg
		In this scenario, it is entirely possible to just ingore the rest of the 6 padding bits, so the "end" of the message is arbitrary
		Also, it seems like host will stop toggling clock all together once the message is done. Does spi clock start after cs_n?

	How do we know when the next message is coming?
		In this case, we could depend on cs_n being pulled down, so this means that every message, the cs_n line drops low and then pulls high once the message is over
		But this creates more questions, such as if we were to output to host, we would need cs_n pulled low, and we would have to write back in a certain amount of time. How will the host know when we are done writing back?
	
	How does the host know when to send the next message (after the 45 rounds?)
		Imagine that we depend on cs_n externally to send a message. We can probably have the host poll the status of the spongent core using the 2 ctrl bits, i.e. read status
		Suppose host requests to read status. If not ready, the returning 8 bits represent busy.
		If ready, then the host would pull cs_n high, then low again to send a data message. Actually, we can probably implement it the following way:
			control[9:8] data[7:0], imagine that the host message is 32 bits, so it needs to send 4 x 8 messages of data
			The first message was successful, 8 bits sent and spongent core becomes busy, returns 8 bits with errno 0 indicating a success
			The host tries to write another 8 bits, but since core is busy, the return output is an errno that represents busy
			The host keeps trying until the output by the core is a 0
			Once all 32 bits are fed in and 0 is returned, the host keeps inquiring status?
				but inquiring status is slow, you need to send 16 total bits only to read 2 of them by the core
				Are we assuming that every time host reads back 8 bits, it needs to send 16 bits first? THen we send 11 messages to core to receive 11 messages back

	How does SPI know when to send output, and how will host know output is ready?
	*/
endmodule
