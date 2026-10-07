`default_nettype none

module spi_controller (
	input wire clk,      // clock
	input wire rst_n,     // reset_n - low to reset

	// these go to top
	input wire cs_n,
	input wire mosi,
	output wire miso,
	input wire sck,

	// these go to core
	output wire rx,
	output wire sck_fall,
	input wire tx
);

	assign rx <= 1'b1;


endmodule
