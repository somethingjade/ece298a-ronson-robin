`default_nettype none
// Hi
module spi_test (
    input wire clk,
    input wire rst_n, 

    input wire rx, 
    input wire sck_rise, 
    input wire sck_fall, 

    output wire tx, 
    output wire start_write,
    output wire error_status
);
    reg output_reg;
    reg input_reg;
    reg [3:0] counter;
    reg [7:0] shift_registers;
    reg read_state;
    reg error_reg;

    assign tx = output_reg;
    assign start_write = read_state;
    assign error_status = error_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            output_reg <= 0;
            input_reg <= 0;
            counter[3:0] <= 0;
            shift_registers[7:0] <= 8'b0;
            read_state <= 0;
            error_reg <= 0;
        end

        if (sck_rise) begin
            
            counter <= counter + 1;
            if (counter > 1) begin
                read_state <= 1;
                output_reg <= 1;
            end 
            if (counter == 15) begin
                read_state <= 0;
                counter <= 0;
                output_reg <= 0;
            end
        end
    end

// 11111111 1111111111 1111111111 1111111111
endmodule 