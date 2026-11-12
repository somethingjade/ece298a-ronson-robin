`default_nettype none

module spi_controller (
	// these go to top
	input wire clk, 		// device clock for all modules
	input wire rst_n,     	// active low to reset

	// required spi signals
	input wire cs_n, 		// active low to select device and begin transaction
	input wire mosi,		// master out, slave in
	output wire miso,		// master in, slave out
	input wire sck, 		// SPI clock, meant to be at least 4 times slower than device clock

	// these go to spongent core
	output wire tx,			// input received from mosi given to spongent core
	input wire rx,			// output received from spongent core given to miso
	output wire sck_fall,	// 1 if a falling edge is detected (for sampling)
	output wire sck_rise,	// 1 if a rising edge is detected (for outputting)
	input wire error_status,// driven by spongent core if entered a bad state
	input start_write 		// driven by spongent core indicating when to start output routine
);

	// synchronization chain
	reg sck_next;
	reg sck_prev;
	reg sck_interface;
	
	reg mosi_next;
	reg mosi_prev;
	reg mosi_interface; // 

	assign sck_rise = (!sck_prev) & sck_next;
	assign sck_fall = (!sck_next) & sck_prev;

	reg [1:0] error_mask; // This register is used to mask the miso output if an error has appeared in either the spi module or the spongent core
	reg [5:0] shift_registers; // Used to delay the output coming from the spongent core to map all 8 bits outputed to the LSByte of the message frame
	reg output_enable;	
	reg beginning_of_write; // For assigning the error mask to the data out

	assign tx = mosi_prev;
	assign miso = shift_registers[5]; 
	wire async_reset = !rst_n || cs_n; // Since I reset state on two reset signals and GDS only allows one reset signal

	always @(posedge clk or posedge async_reset) begin
		error_mask[1] <= error_status;
		output_enable <= start_write;
		
		if (!rst_n | cs_n) begin
			sck_next <= 0; // in SPI mode 1, the clock is idle when low
			sck_prev <= 0;
			sck_interface <= 0;

			mosi_next <= 0;
			mosi_prev <= 0;
			mosi_interface <= 0;
			
			error_mask[1:0] <= 2'b0;
			output_enable <= 0;
			shift_registers[5:0] <= 6'b0;
			beginning_of_write <= 1;
		end else begin
			if (!cs_n) begin // MOSI only read if chip select low
				sck_prev <= sck_next;
				sck_next <= sck_interface;
				sck_interface <= sck;
				
				mosi_prev <= mosi_next;
				mosi_next <= mosi_interface;
				mosi_interface <= mosi;

				// Example of expected input and output
				// INPUT:  1000 0000 01-- ---- (ctrl: 10, data: 0000 0001, padding: -- ----)
				// OUTPUT: ---- --00 1010 1100 (err_stat: 00, data: 0010 1011, padding: ---- --)
				
				if (output_enable) begin // output_enable should only be on if host requests data or status, and this is set on a falling edge!
					if (beginning_of_write) begin
						shift_registers[0] <= error_mask[0]; // error values are tracked all the time when device is not communicating with host
						shift_registers[1] <= error_mask[1];
						beginning_of_write <= 0;
						// Won't shift_registers[0] be overwritten by rx later?
						// No, because output_enable is driven on a falling edge, so the SR value is already clocked
						// before sck_rise triggers! Of course, this depends on the assumption that spi clock is slower than device clock
					end
					if (sck_rise) begin
						shift_registers[5] <= shift_registers[4];
						shift_registers[4] <= shift_registers[3];
						shift_registers[3] <= shift_registers[2];
						shift_registers[2] <= shift_registers[1];
						shift_registers[1] <= shift_registers[0];
						shift_registers[0] <= rx;
					end
				end

			end
		end
	end

endmodule