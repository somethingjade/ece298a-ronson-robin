import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge
from cocotbext.spi import SpiBus, SpiConfig, SpiMaster
from cocotb.triggers import ClockCycles
from cocotb.types import Logic



@cocotb.test()
async def test_project(dut):
    # 1. Start the system clock (assuming your DUT has an independent system clock)
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # 2. Reset the DUT    
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    # 3. Map the SPI signals to the SpiBus object
    # Matches your DUT's port names: sclk, mosi, miso, cs_n
    # 1. Define your custom wire mapping

    # 2. Pass your DUT and the mapping dictionary to SpiBus
    spi_bus = SpiBus.from_prefix(dut, prefix="spi")
    # 4. Configure the SPI Protocol (e.g., Mode 1: CPOL=0, CPHA=1)
    spi_config = SpiConfig(
        sclk_freq=10000000,
        word_width=16,
        cpol=False,
        cpha=True,
        msb_first=True,
        cs_active_low=True
    )

    # 5. Instantiate the SPI Master driver
    spi_master = SpiMaster(spi_bus, spi_config)

    # 6. Perform a Full-Duplex Transfer
    tx_data = [0x0000, 0x4000, 0x8000, 0xc000]
    dut._log.info(f"{' '.join(f'{num:b}' for num in tx_data)}")
    
    # This coroutine blocks until the entire SPI transaction finishes
    spi_master.write_nowait(tx_data)

    await spi_master.wait()
    
    # 2. Read back the full-duplex response bytes from the receive buffer
    rx_data = await spi_master.read()
    
    # print(f"Received data from Slave DUT: {list(rx_data)}")
    if (isinstance(rx_data, type(None))):
        assert False, "rx_data was none!"
    dut._log.info(f"{' '.join(f'{num:b}' for num in rx_data)}")
    

    # 7. Check if results match expectations
    assert rx_data[0] == 0x0000
    assert rx_data[1] == 0x00FF