# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, FallingEdge


@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # Set the clock period to 10 us (100 KHz)
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    dut._log.info("Test project behavior")

    # Set the input values you want to test
    # dut.ui_in.value = 20
    # dut.uio_in.value = 30
    

    # Wait for one clock cycle to see the output values
    await ClockCycles(dut.clk, 1)

    # a = await send_command(dut, 0b1100000000000000)
    # assert a == 1

    a = await send_command(dut, 0b0001100111000000)
    assert a == 32
    assert dut.user_project.spongent.state.value == 0x67


    # The following assersion is just an example of how to check the output values.
    # Change it to match the actual expected output of your module:
    # assert dut.uo_out.value == 50

    # Keep testing the module by changing the input values, waiting for
    # one or more clock cycles, and asserting the expected output values.

async def send_command(dut, command):
    ret = 0
    await FallingEdge(dut.clk)
    for i in range(16):
        bit = (((command << i) & 0x8000) >> 12)
        await ClockCycles(dut.clk, 4)
        dut.uio_in.value = (bit | 0b00000001) & 0xFF
        await ClockCycles(dut.clk, 1)
        # dut._log.info("i=%d, rx=%d, out=%d",
        #       i,
        #       int(dut.uio_in.value) >> 3 & 1,
        #       int(dut.uio_out.value) >> 2 & 1)
        dut.uio_in.value = (bit | 0b00000000) & 0xFF
        await ClockCycles(dut.clk, 4)
        dut.uio_in.value = (bit | 0b00000010) & 0xFF
        await ClockCycles(dut.clk, 1)
        dut.uio_in.value = (bit | 0b00000000) & 0xFF
        ret = (ret << 1) | (int(dut.uio_out.value) >> 2 & 0x01)

    return (ret >> 6) & 0xFF
        
