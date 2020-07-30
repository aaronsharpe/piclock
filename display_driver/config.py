import os
import logging
import sys
import time
import spidev as SPI
import RPi.GPIO as GPIO


class RaspberryPi:
    def __init__(self):
        # pins used for buttons: 4, 5, 6, 12, 13, 16, 17, 20, 21, 22, 23, 26
        # Other pins: 2, 3, 7, 8, 9, 10, 11, 14, 15, 19, 24,
        # GPIOS 0-8 are pulled high
        self.RST_PIN = 27
        self.DC_PIN = 25
        self.BL_PIN = 18
        self.CS_PIN = 18

        # SPI device, bus = 0, device = 0

    def digital_write(self, pin, value):
        self.GPIO.output(pin, value)

    def digital_read(self, pin):
        return self.GPIO.input(pin)

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        self.SPI.writebytes(data)

    def module_init(self):

        self.GPIO = GPIO
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setwarnings(False)
        self.GPIO.setup(self.RST_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.DC_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.BL_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.CS_PIN, self.GPIO.OUT)

        self.SPI = SPI.SpiDev(0, 0)
        self.SPI.mode = 0b00
        self.SPI.max_speed_hz = 90000000

    def module_exit(self):
        logging.debug("spi end")
        self.SPI.close()

        logging.debug("close 5V, Module enters 0 power consumption ...")
        self.GPIO.output(self.RST_PIN, 0)
        self.GPIO.output(self.DC_PIN, 0)

        self.GPIO.cleanup()
