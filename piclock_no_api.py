import asyncio
import pigpio
import time
import sys
import os
import json
from itertools import cycle
import aiohttp
from aiohttp import ClientSession
from PIL import Image, ImageDraw, ImageFont
from display_driver import ST7789
from enum import IntEnum


# TODO
# async
# retry+backoff for get post
# reboot
# autodim
# calendar
# cpu monitor
# weather
# scrolling spotify text
# launching on startup


class ButtonState(IntEnum):
    UNHELD = 0
    PRESSED = 1
    HELD = 2
    RELEASED = 3


async def display_time(disp, color):
    current_time, current_date = fetch_time()

    time_date_screen = Image.new('RGB', (disp.height, disp.width), (0, 0, 0))
    draw = ImageDraw.Draw(time_date_screen)

    # Time
    font = ImageFont.truetype('Minecraftia.ttf', 48)
    _, str_width = string_dims(draw, font, current_time)
    x_pos = (disp.height/2)-str_width/2
    y_pos = 10
    draw.text((x_pos, y_pos), current_time, font=font, fill=color)

    # Date
    font = ImageFont.truetype('Minecraftia.ttf', 16)
    _, str_width = string_dims(draw, font, current_date)
    x_pos = (disp.height/2)-str_width/2
    y_pos = (disp.width)/16 + 60
    draw.text((x_pos, y_pos), current_date, font=font, fill=color)

    time_date_screen = time_date_screen.rotate(180)
    disp.ShowImage(time_date_screen)


async def display_network(disp, net_info, color):
    network_screen = Image.new('RGB', (disp.height, disp.width), (0, 0, 0))
    draw = ImageDraw.Draw(network_screen)
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)

    # SSID
    font = ImageFont.truetype('Minecraftia.ttf', 16)
    x_pos = 2
    y_pos = 2
    draw.text((x_pos, y_pos), net_info[0], font=font, fill=color)

    # IP
    font = ImageFont.truetype('Minecraftia.ttf', 16)
    y_pos += 30
    draw.text((x_pos, y_pos), "IP: "+net_info[1], font=font, fill=color)

    # GW
    y_pos += 30
    draw.text((x_pos, y_pos), "GW: "+net_info[2], font=font, fill=color)

    network_screen = network_screen.rotate(180)
    disp.ShowImage(network_screen)


async def display_custom(disp, text, color):
    custom_screen = Image.new('RGB', (disp.height, disp.width), (0, 0, 0))
    draw = ImageDraw.Draw(custom_screen)
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)

    font = ImageFont.truetype('Minecraftia.ttf', 16)
    x_pos = 2
    y_pos = 2
    draw.text((x_pos, y_pos), text, font=font, fill=color)

    custom_screen = custom_screen.rotate(180)
    disp.ShowImage(custom_screen)


async def string_dims(draw, fontType, string):
    string_height = 0
    string_width = 0

    for c in string:
        char_width, char_height = draw.textsize(c, font=fontType)
        string_height += char_height
        string_width += char_width

    return string_height, string_width


async def fetch_time():
    current_time = time.strftime('%H:%M')
    current_date = time.strftime('%m/%d/%Y')
    return current_time, current_date


async def check_button_state(pi, button_state, button_to_pin):
    for button in button_state.keys():
        if not pi.read(button_to_pin[button]):
            if not button_state[button]:
                button_state[button] = ButtonState.PRESSED
            else:
                button_state[button] = ButtonState.HELD
        else:
            if button_state[button]:
                button_state[button] = ButtonState.RELEASED
            else:
                button_state[button] = ButtonState.UNHELD
    await asyncio.sleep(0.01)
    return button_state


async def button_release_handler(disp, pi, clock_state, cyclers, button):
    if button == 'L':
        bl_dc = next(cyclers['bl_dc'])
        clock_state['bl_dc'] = bl_dc
        pi.set_PWM_dutycycle(24, bl_dc)
        return clock_state, False
    elif button == 'R':
        color = next(cyclers['color'])
        clock_state['color'] = color
        return clock_state, True
    elif button == 'start':
        display = next(cyclers['display'])
        clock_state['display'] = display
        return clock_state, True
    elif button == 'select':
        if display == 'home':
            return clock_state, False
        elif display == 'network':
            # Reconnect to network
            display_custom(disp, 'reconnecting...', color)
            os.popen(
                'sudo ip link set wlan0 down; sleep 5; sudo ip link set wlan0 up')
            await asyncio.sleep(0.1)
            clock_state['net_info'] = ('ssid', 'ipaddress', 'gateway')
            await asyncio.sleep(0.1)
            return clock_state, True
        elif display == 'custom':
            return clock_state, False


async def slow_test_function():
    print('in the slow test function')
    await asyncio.sleep(1)


async def main():
    # Init pins and buttons
    pi = pigpio.pi()
    pi.set_mode(24, pigpio.OUTPUT)
    pi.set_PWM_dutycycle(24, 100)

    pi.set_pull_up_down(5, pigpio.PUD_UP)  # L
    pi.set_pull_up_down(6, pigpio.PUD_UP)  # R
    pi.set_pull_up_down(26, pigpio.PUD_UP)  # start
    pi.set_pull_up_down(16, pigpio.PUD_UP)  # select

    button_state = {'L': ButtonState.UNHELD, 'R': ButtonState.UNHELD,
                    'start': ButtonState.UNHELD, 'select': ButtonState.UNHELD}
    button_to_pin = {'L': 5, 'R': 6, 'start': 26, 'select': 16}

    # Initialize display
    disp = ST7789.ST7789()
    disp.clear()
    blank_screen = Image.new('RGB', (disp.height, disp.width), (0, 0, 0))
    disp.ShowImage(blank_screen)
    update_display = True

    # Cycling variables
    bl_cycle = cycle([0, 5, 10, 25, 50, 75, 100])
    display_cycle = cycle(['home', 'network', 'custom'])
    color_cycle = cycle(['WHITE', 'RED', 'GREEN', 'BLUE'])

    clock_state = {'display': next(display_cycle),
                   'bl_dc': 100, 'color': next(color_cycle)}
    cyclers = {'display': display_cycle,
               'bl_dc': bl_cycle, 'color': color_cycle}

    clock_prev = time.strftime('%H:%M')
    clock_state['time'] = clock_prev
    clock_state['net_info'] = ('ssid', 'ipaddress', 'gateway')

    while True:
        button_state = await check_button_state(pi, button_state, button_to_pin)

        for button in button_state.keys():
            if button_state[button] == ButtonState.RELEASED:
                clock_state, update_display = await button_release_handler(
                    disp, pi, clock_state, cyclers, button)

        clock_cur = time.strftime('%H:%M')
        if clock_cur != clock_state['time']:
            update_display = True
            clock_state['time'] = clock_cur

        if update_display:
            update_display = False
            if(clock_state['display'] == 'home'):
                await display_time(disp, clock_state['color'])
            elif(clock_state['display'] == 'network'):
                await display_network(
                    disp, clock_state['net_info'], clock_state['color'])
            elif(clock_state['display'] == 'custom'):
                await display_custom(disp, 'fetching data...', clock_state['color'])

loop = asyncio.get_event_loop()
loop.create_task(main())
loop.run_forever()
