/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_spongent88_top (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);
	wire rx, sck_fall, tx;
	wire miso;

	spi_controller spi (
		.clk(clk),
		.rst_n(rst_n),
		.cs_n(uio_in[0]),
		.mosi(uio_in[1]),
		.miso(miso),
		.sck(uio_in[3]),
		.rx(rx),
		.sck_fall(sck_fall),
		.tx(tx)
	);

	spongent88_core spongent (
		.clk(clk),
		.rst_n(rst_n),
		.rx(rx),
		.sck_fall(sck_fall),
		.tx(tx)
	);

  // All output pins must be assigned. If not used, assign to 0.
  // assign uo_out  = ui_in + uio_in;  // Example: ou_out is the sum of ui_in and uio_in
  assign uo_out = 0;
  assign uio_out = { 5'b0, miso, 2'b0 };
  assign uio_oe  = 8'b00000100;

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, clk, rst_n, 1'b0};

endmodule
