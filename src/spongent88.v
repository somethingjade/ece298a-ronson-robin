`default_nettype none

module spongent88_core (
    input wire clk,      // clock
    input wire rst_n,     // reset_n - low to reset

    input wire rx, // synchronized data bit from spi
    input wire sck_fall, // sck falling edge. used to synchronize with spi

    output wire tx // bit to be sent over miso
);

	localparam IDLE = 3'b000;
	localparam ABSORB = 3'b001;
	localparam LFSR = 3'b010;
	localparam SBOX = 3'b011;
	localparam PLAYER = 3'b100;
	localparam SQUEEZE = 3'b101;

	(* keep = "true" *) reg [2:0] fsm_state;

	reg [1:0] command;
	reg [7:0] miso;

	reg [3:0] msg_counter;
	reg [5:0] counter;

	(* keep = "true" *) reg [87:0] state;

	always @(posedge clk or negedge rst_n) begin
		if (!rst_n) begin
			fsm_state <= IDLE;
			command <= 2'b0;
			miso <= 8'b0;
			msg_counter <= 4'b0;
			counter <= 6'b0;
			state <= 88'b0;
		end else begin
			if (sck_fall) begin
				// read in new bit
				if (fsm_state != ABSORB && fsm_state != SQUEEZE) begin
					if (msg_counter < 2) begin
						command <= { command[0], rx };
					end
				end

				msg_counter <= msg_counter == 9 ? 0 : msg_counter + 1;

				// 2 most significant message bits received
				// handle
				if (msg_counter == 1) begin
					case ({ command[0], rx })
						// write data
						2'b00: begin
							if (fsm_state == IDLE) begin
								fsm_state <= ABSORB;
							end else begin
								// error
								miso <= 8'b11111111;
							end
						end
						// write control
						2'b01: begin
							// TODO: implement this
						end
						// read data
						2'b10: begin
							// TODO: implement
						end
						// read status
						2'b11: begin
							miso <= (fsm_state == IDLE) ? 8'b00000000 : 8'b10000000;
						end
						default: begin
						end
					endcase
				end else begin
					miso <= { miso[6:0], 1'b0 };
				end
			end

			case (fsm_state)
				ABSORB: begin
					if (counter < 8) begin
						if (sck_fall) begin
							state <= { state[87:8], state[7:0] ^ (rx << (7 - counter[2:0])) };
							counter <= counter + 1;
						end
					end else begin
						counter <= 6'b0;
						fsm_state <= LFSR;
					end
				end
				IDLE, LFSR, SBOX, PLAYER, SQUEEZE: begin
					fsm_state <= IDLE;
				end
				default: begin
					fsm_state <= IDLE;
				end
			endcase
		end
	end

	assign tx = miso[7];

endmodule
