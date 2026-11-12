`default_nettype none

module spongent88_core (
	input wire clk,      // clock
	input wire rst_n,     // reset_n - low to reset

	input wire rx, // synchronized data bit from spi
	input wire sck_fall, // sck falling edge. used to synchronize with spi
	input wire sck_rise, // sck falling edge. used to synchronize with spi

	output wire tx, // bit to be sent over miso
	output wire error_status,// driven by spongent core if entered a bad state
	output wire start_write // driven by spongent core indicating when to start output routine
);

	localparam IDLE = 3'b000;
	localparam ABSORB = 3'b001;
	localparam LFSR = 3'b010;
	localparam SBOX = 3'b011;
	localparam PLAYER = 3'b100;

	localparam WRITE_DATA = 2'b00;
	localparam WRITE_CONTROL = 2'b01;
	localparam READ_DATA = 2'b10;
	localparam READ_STATUS = 2'b11;

	integer sbox_nibble;
	integer read_byte;

	reg [2:0] fsm_state;

	reg [1:0] command;
	reg [7:0] control;
	reg [7:0] miso;

	reg [3:0] msg_counter;
	reg [5:0] counter;
	reg [4:0] sbox_counter;

	reg [87:0] state;
	reg [5:0] lfsr;
	wire [5:0] lfsr_reversed = { lfsr[0], lfsr[1], lfsr[2], lfsr[3], lfsr[4], lfsr[5] };

	wire[3:0] control_read_byte = { control[7:4] };
	wire[2:0] control_breakpoint = { control[3:1] };
	wire control_reset = { control[0] };

	function [5:0] increment_lfsr;
		input [5:0] lfsr;
		begin
			increment_lfsr = { lfsr[4:0], lfsr[5] ^ lfsr[4] };
		end
	endfunction

	function [3:0] sbox;
		input [3:0] x;
		begin
			case (x)
				4'h0: sbox = 4'hE;
				4'h1: sbox = 4'hD;
				4'h2: sbox = 4'hB;
				4'h3: sbox = 4'h0;
				4'h4: sbox = 4'h2;
				4'h5: sbox = 4'h1;
				4'h6: sbox = 4'h4;
				4'h7: sbox = 4'hF;
				4'h8: sbox = 4'h7;
				4'h9: sbox = 4'hA;
				4'hA: sbox = 4'h8;
				4'hB: sbox = 4'h5;
				4'hC: sbox = 4'h9;
				4'hD: sbox = 4'hC;
				4'hE: sbox = 4'h3;
				4'hF: sbox = 4'h6;
				default: sbox = 4'h0;
			endcase
		end
	endfunction

	function [6:0] P;
		input [6:0] j; // maximum 88
		begin
			if (j == 87) begin
				P = 87; // index = 87
			end else begin
				P = j*22 % 87; // index = j*22 % 87
			end
		end
	endfunction

	always @(posedge clk or negedge rst_n) begin
		if (!rst_n) begin
			fsm_state <= IDLE;
			command <= 2'b0;
			control <= 8'b0;
			miso <= 8'b0;
			msg_counter <= 4'b0;
			counter <= 6'b0;
			sbox_counter <= 5'b0;
			state <= 88'b0;
			lfsr <= 6'b000101;
		end else begin
			if (sck_rise) begin
				// 2 most significant message bits received
				// handle
				if (msg_counter == 2) begin
					case (command)
						// write data
						WRITE_DATA: begin
							if (fsm_state == IDLE) begin
								fsm_state <= ABSORB;
								// no error
								miso[7] <= 1'b0;
								// busy
								miso[6] <= 1'b1;
								miso[5:0] <= counter;
							end else begin
								// error
								miso[7] <= 1'b1;
								// busy
								miso[6] <= 1'b1;
								miso[5:0] <= counter;
							end
						end
						// write control
						WRITE_CONTROL: begin
							miso[7] <= 0; // no error for now?
							// busy if not idle
							miso[6] <= fsm_state != IDLE;
							miso[5:0] <= counter;
						end
						// read data
						READ_DATA: begin
							// should make sure
							// hash is not in
							// progress. for now,
							// it's like this for
							// testing.
							read_byte = ((control_read_byte < 11) ? control_read_byte : 0) * 8;
							miso <= state[read_byte +: 8];
						end
						// read status
						READ_STATUS: begin
							miso[7] <= 0; // no error for now?
							// busy if not idle
							miso[6] <= fsm_state != IDLE;
							miso[5:0] <= counter;
						end
						default: begin
						end
					endcase
				end else begin
					miso <= { miso[6:0], 1'b0 };
				end
			end else if (sck_fall) begin
				// read in new bit
				if (fsm_state != ABSORB) begin // Why not just put IDLE? Do we allow fsm transition during other states? 
				// Ah I get it, because during the rest of the computation, the host may still want to inquire the system status, so as long as it's not
				// absorbing or squeezing, 
					if (msg_counter < 2) begin
						command <= { command[0], rx }; // command[0] dictates read or write state. Who is writing to that?
						// the if block triggers for the first two MSB of the message, but then the command always becomes write data, write control, and never read
						// I'm assuming Ronson used command[0] for testing purposes
					end else if (command == WRITE_CONTROL && msg_counter < 10) begin
						control <= { control[6:0], rx };
					end
				end
				msg_counter <= msg_counter + 1;
			end

			if (msg_counter == 0 && control_reset) begin
				fsm_state <= IDLE;
				command <= 2'b0;
				control <= 8'b0;
				miso <= 8'b0;
				msg_counter <= 4'b0;
				counter <= 6'b0;
				sbox_counter <= 5'b0;
				state <= 88'b0;
				lfsr <= 6'b000101;
			end else begin
				case (fsm_state)
					IDLE: begin
					end
					ABSORB: begin
						if (counter < 8) begin
							if (sck_fall) begin
								state <= { state[87:8], state[7:0] ^ (rx << (7 - counter[2:0])) };
								counter <= counter + 1;
							end
						end else begin
							counter <= 6'b0;
							lfsr <= 6'b000101;
							if (control_breakpoint != ABSORB) begin
								fsm_state <= LFSR;
							end
						end
					end
					LFSR: begin
						state <= { state[87:82] ^ lfsr_reversed, state[81:6], state[5:0] ^ lfsr };
						lfsr <= increment_lfsr(lfsr);
						sbox_counter <= 0;
						if (control_breakpoint != LFSR) begin
							fsm_state <= SBOX;
						end
					end
					SBOX: begin
						if (sbox_counter < 22) begin
							sbox_nibble = sbox_counter * 4;
							state[sbox_nibble +: 4] <= sbox(state[sbox_nibble +: 4]);
							if (sbox_counter == 21) begin
								sbox_counter <= 0;
								if (control_breakpoint != SBOX) begin
									fsm_state <= PLAYER;
								end
							end else begin
								sbox_counter <= sbox_counter + 1;
							end
						end
					end
					PLAYER: begin
						reg[6:0] j;
						for (j = 0; j < 87; j = j + 1) begin
							state[P(j)] <= state[j];
						end
						// Why does this work?
						// Verilog recognizes that this can be done in parallel using combinational all in the same clock

						if (counter < 45) begin
							fsm_state <= LFSR;
							counter <= counter + 1; // Reuse counter to perform 45 rounds
						end else begin
							fsm_state <= SQUEEZE;
						end
						if (control_breakpoint != PLAYER) begin
							fsm_state <= IDLE;
						end
					end
					default: begin
						fsm_state <= IDLE;
					end
				endcase
			end
		end
	end

	assign tx = miso[7];
	assign error_status = 1'b0; // not using this rn
	assign start_write = msg_counter >= 2 && msg_counter <= 10;

endmodule


