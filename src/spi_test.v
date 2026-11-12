`default_nettype none
// Test Module for spi.v only
module spi_test (
    input wire clk,
    input wire rst_n, 
    input wire rx, 
    output wire tx, 
    input wire sck_rise, 
    input wire sck_fall, 
    output wire start_write,
    output wire error_status
);
    reg output_reg;
    reg is_in_read_state;
    reg error_reg;
    reg [3:0] counter;
    reg [1:0] shift_registers; // Not used in this module

    assign tx = output_reg;
    assign start_write = is_in_read_state;
    assign error_status = error_reg;

    // Simulate spongent FSM
    always @(posedge clk or negedge rst_n) begin 
        if (!rst_n) begin
            output_reg <= 0;
            counter[3:0] <= 0;
            shift_registers[1:0] <= 2'b0;
            is_in_read_state <= 0;
            error_reg <= 0;
        end else if (sck_fall) begin // Sample on falling edge
            counter <= counter + 1;
            if (counter < 2) begin
                shift_registers[1] <= shift_registers[0];
                shift_registers[0] <= rx;
            end else if (counter >= 2) begin // Simulate reading 2 CTRL bits
                
                if (shift_registers == 0) begin
                    is_in_read_state <= 0;
                    output_reg <= 0;
                end else if (shift_registers == 1) begin
                    is_in_read_state <= 0;
                    output_reg <= 1;
                end else if (shift_registers == 2) begin
                    is_in_read_state <= 1;
                    output_reg <= 1;
                end else if (shift_registers == 3) begin
                    is_in_read_state <= 1;
                    output_reg <= rx;
                end
            end 
            if (counter == 15) begin // Clear registers after a full message frame
                is_in_read_state <= 0;
                counter <= 0;
                output_reg <= 0;
            end
        end
    end

endmodule 