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


def display_time(disp, spotify_state, color):
    current_time = time.strftime('%H:%M')
    current_date = time.strftime('%m/%d/%Y')

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

    if spotify_state['is_playing']:
        font = ImageFont.truetype('Minecraftia.ttf', 16)
        x_pos = 2
        y_pos = 170
        draw.text((x_pos, y_pos),
                  spotify_state['song_title'], font=font, fill=color)

        y_pos += 30
        draw.text((x_pos, y_pos),
                  spotify_state['artist'], font=font, fill=color)

    time_date_screen = time_date_screen.rotate(180)
    disp.ShowImage(time_date_screen)


def display_network(disp, net_info, color):
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


def display_custom(disp, text, color):
    custom_screen = Image.new('RGB', (disp.height, disp.width), (0, 0, 0))
    draw = ImageDraw.Draw(custom_screen)
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)

    font = ImageFont.truetype('Minecraftia.ttf', 16)
    x_pos = 2
    y_pos = 2
    draw.text((x_pos, y_pos), text, font=font, fill=color)

    custom_screen = custom_screen.rotate(180)
    disp.ShowImage(custom_screen)


def string_dims(draw, fontType, string):
    string_height = 0
    string_width = 0

    for c in string:
        char_width, char_height = draw.textsize(c, font=fontType)
        string_height += char_height
        string_width += char_width

    return string_height, string_width


async def api_handler(api_info, spotify_state):
    api_info, spotify_state = await fetch_spotify(api_info, spotify_state)
    return api_info, spotify_state


async def fetch_spotify(api_info, spotify_state):
    url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {'Authorization': 'Bearer ' + api_info['spotify_access_token'],
               'Accept': 'application/json', 'Content-Type': 'application/json'}

    async with aiohttp.ClientSession() as session:
        resp = await session.request(method='GET', url=url, headers=headers)

    if resp.status == 204:  # valid access code, not active
        return api_info, {'is_playing': False, 'artist': '', 'song_title': ''}
    elif resp.status == 200:  # valid access code, active
        data = await resp.json()
        is_playing = data['is_playing']
        artist = data['item']['artists'][0]['name']
        song_title = data['item']['name']
        spotify_state = {'is_playing': is_playing,
                         'artist': artist, 'song_title': song_title}
        return api_info, spotify_state
    else:  # invalid access code or other error
        print('Spotify request failed error:' + str(resp.status))
        api_info = await refresh_spotify_access_token(api_info)
        spotify_state = {'is_playing': False, 'artist': '', 'song_title': ''}
        return api_info, spotify_state


async def refresh_spotify_access_token(api_info):
    url = 'https://accounts.spotify.com/api/token'
    headers = {'Authorization': 'Basic ' +
               api_info['spotify_id_secret_encoded']}
    data = {'grant_type': 'refresh_token',
            'refresh_token': api_info['spotify_refresh_token']}

    async with aiohttp.ClientSession() as session:
        p = await session.request(method='POST', url=url, data=data, headers=headers)

    pjson = await p.json()
    api_info['spotify_access_token'] = pjson['access_token']

    with open('.api_info.json', 'w') as f:
        json.dump(api_info, f)
    return api_info


async def fetch_net_info():
    # Collect network information by parsing command line outputs
    async with aiohttp.ClientSession() as session:
        resp = await session.request(method='GET', url='https://api.ipify.org')
    ipaddress = await resp.text()

    # netmask = os.popen("ifconfig wlan0 | grep 'Mask' | awk -F: '{print $4}'").read()
    gateway = os.popen("route -n | grep '^0.0.0.0' | awk '{print $2}'").read()
    ssid = os.popen(
        "iwconfig wlan0 | grep 'ESSID' | awk '{print $4}' | awk -F\\\" '{print $2}'").read()

    return (ssid, ipaddress, gateway)


async def button_handler(pi, disp, button_state, button_to_pin, clock_state, cyclers):
    button_state = await check_button_state(pi, button_state, button_to_pin)

    for button in button_state.keys():
        if button_state[button] == ButtonState.PRESSED:
            clock_state = await button_press_handler(
                disp, pi, clock_state, cyclers, button)
    return clock_state


async def check_button_state(pi, button_state, button_to_pin):
    for button in button_state.keys():
        if not pi.read(button_to_pin[button]):
            if button_state[button] == ButtonState.UNHELD:
                button_state[button] = ButtonState.PRESSED
            elif button_state[button] == ButtonState.PRESSED or button_state[button] == ButtonState.HELD:
                button_state[button] = ButtonState.HELD
        else:
            if button_state[button] == ButtonState.PRESSED or button_state[button] == ButtonState.HELD:
                button_state[button] = ButtonState.RELEASED
            elif button_state[button] == ButtonState.RELEASED or button_state[button] == ButtonState.UNHELD:
                button_state[button] = ButtonState.UNHELD

    return button_state


async def button_press_handler(disp, pi, clock_state, cyclers, button):
    if button == 'L':
        bl_dc = next(cyclers['bl_dc'])
        clock_state['bl_dc'] = bl_dc
        pi.set_PWM_dutycycle(24, bl_dc)
        return clock_state
    elif button == 'R':
        color = next(cyclers['color'])
        clock_state['color'] = color
        clock_state['update_display'] = True
        return clock_state
    elif button == 'start':
        display = next(cyclers['display'])
        clock_state['display'] = display
        clock_state['update_display'] = True
        return clock_state
    elif button == 'select':
        if display == 'home':
            return clock_state
        elif display == 'network':
            # Reconnect to network
            display_custom(disp, 'reconnecting...', color)
            os.popen(
                'sudo ip link set wlan0 down; sleep 5; sudo ip link set wlan0 up')
            await asyncio.sleep(0.1)
            clock_state['net_info'] = await fetch_net_info()
            await asyncio.sleep(0.1)
            clock_state['update_display'] = True
            return clock_state
        elif display == 'custom':
            return clock_state


async def display_handler(disp, clock_state, spotify_state):
    print(clock_state['update_display'])
    print(spotify_state)
    print(clock_state)
    clock_cur = time.strftime('%H:%M')
    if clock_cur != clock_state['time']:
        clock_state['update_display'] = True
        clock_state['time'] = clock_cur

    if spotify_state['is_playing']:
        clock_state['update_display'] = True

    if clock_state['update_display']:
        clock_state['update_display'] = False
        if(clock_state['display'] == 'home'):
            display_time(disp, spotify_state, clock_state['color'])
        elif(clock_state['display'] == 'network'):
            display_network(
                disp, clock_state['net_info'], clock_state['color'])
        elif(clock_state['display'] == 'custom'):
            display_custom(disp, 'fetching data...', clock_state['color'])


async def periodic_task(tau, f, *args):
    while True:
        await f(*args)
        await asyncio.sleep(tau)


def main():
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

    # Cycling variables
    bl_cycle = cycle([0, 5, 10, 25, 50, 75, 100])
    display_cycle = cycle(['home', 'network', 'custom'])
    color_cycle = cycle(['WHITE', 'RED', 'GREEN', 'BLUE'])

    clock_state = {'display': next(display_cycle),
                   'bl_dc': 100, 'color': next(color_cycle)}
    clock_state['update_display'] = True
    cyclers = {'display': display_cycle,
               'bl_dc': bl_cycle, 'color': color_cycle}

    loop = asyncio.get_event_loop()

    # Initial fetching
    with open('.api_info.json', 'r') as f:
        api_info = json.load(f)
    spotify_state = {'is_playing': False, 'artist': '', 'song_title': ''}
    #api_info, spotify_state = loop.run_until_complete(fetch_spotify(api_info))
    clock_prev = time.strftime('%H:%M')
    clock_state['time'] = clock_prev
    clock_state['net_info'] = loop.run_until_complete(fetch_net_info())

    # Setup and run event loop

    loop.create_task(periodic_task(
        0.01, button_handler, pi, disp, button_state, button_to_pin, clock_state, cyclers))

    loop.create_task(periodic_task(1, api_handler, api_info, spotify_state))

    loop.create_task(periodic_task(
        0.1, display_handler, disp, clock_state, spotify_state))

    try:
        loop.run_forever()
    except(KeyboardInterrupt, SystemExit):
        loop.stop()


if __name__ == '__main__':
    main()
