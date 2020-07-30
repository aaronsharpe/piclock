import pigpio
import time
import sys
import os
import json
from itertools import cycle
from requests import get, post
from PIL import Image, ImageDraw, ImageFont
from display_driver import ST7789


# TODO reboot, Spotify, calendar?, cpu monitor, weather


def display_time(spotify_state, color):
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


def display_network(net_info, color):
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


def display_custom(text, color):
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


def button_release_handler(pi, clock_state, cyclers, button):
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
            display_custom('reconnecting...', color)
            os.popen(
                'sudo ip link set wlan0 down; sleep 5; sudo ip link set wlan0 up')
            time.sleep(0.1)
            clock_state['net_info'] = fetch_net_info()
            time.sleep(0.1)
            return clock_state, True
        elif display == 'custom':
            return clock_state, False


def fetch_net_info():
    # Collect network information by parsing command line outputs
    ipaddress = get('https://api.ipify.org').text
    # netmask = os.popen("ifconfig wlan0 | grep 'Mask' | awk -F: '{print $4}'").read()
    gateway = os.popen("route -n | grep '^0.0.0.0' | awk '{print $2}'").read()
    ssid = os.popen(
        "iwconfig wlan0 | grep 'ESSID' | awk '{print $4}' | awk -F\\\" '{print $2}'").read()

    return (ssid, ipaddress, gateway)


def fetch_time():
    current_time = time.strftime('%H:%M')
    current_date = time.strftime('%m/%d/%Y')
    return current_time, current_date


def fetch_spotify(api_info):
    url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {'Authorization': 'Bearer ' + api_info['spotify_access_token'],
               'Accept': 'application/json', 'Content-Type': 'application/json'}
    r = get(url, headers=headers)
    if r.status_code == 204:  # valid access code, not active
        return api_info, {'is_playing': False, 'artist': '', 'song_title': ''}
    elif r.status_code == 200:  # valid access code, active
        data = json.loads(r.text)
        is_playing = data['is_playing']
        artist = data['item']['artists'][0]['name']
        song_title = data['item']['name']
        return api_info, {'is_playing': is_playing, 'artist': artist, 'song_title': song_title}
    else:  # invalid access code or other error
        print(r.status_code)
        api_info = refresh_spotify_access_token(api_info)
        return api_info, {'is_playing': False, 'artist': '', 'song_title': ''}


def refresh_spotify_access_token(api_info):
    url = 'https://accounts.spotify.com/api/token'
    headers = {'Authorization': 'Basic ' +
               api_info['spotify_id_secret_encoded']}
    data = {'grant_type': 'refresh_token',
            'refresh_token': api_info['spotify_refresh_token']}
    p = post(url, data=data, headers=headers)
    api_info['spotify_access_token'] = json.loads(p.text)['access_token']

    with open('.api_info.json', 'w') as f:
        json.dump(api_info, f)
    return api_info


# Init pins and buttons
pi = pigpio.pi()
pi.set_mode(24, pigpio.OUTPUT)
pi.set_PWM_dutycycle(24, 100)

pi.set_pull_up_down(5, pigpio.PUD_UP)  # L
pi.set_pull_up_down(6, pigpio.PUD_UP)  # R
pi.set_pull_up_down(26, pigpio.PUD_UP)  # start
pi.set_pull_up_down(16, pigpio.PUD_UP)  # select

button_press = {'L': False, 'R': False, 'start': False, 'select': False}
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
cyclers = {'display': display_cycle, 'bl_dc': bl_cycle, 'color': color_cycle}

# Initial fetching
with open('.api_info.json', 'r') as f:
    api_info = json.load(f)
api_info, spotify_state = fetch_spotify(api_info)
clock_prev, _ = fetch_time()
clock_state['time'] = clock_prev
clock_state['net_info'] = fetch_net_info()


# time constants
tau_spotify = 1
time_prev = time.time()

while True:
    for button in button_press.keys():
        if not pi.read(button_to_pin[button]):
            if not button_press[button]:  # initial press
                button_press[button] = True
            else:  # held down
                pass
        else:
            if button_press[button]:  # release
                button_press[button] = False
                clock_state, update_display = button_release_handler(
                    pi, clock_state, cyclers, button)
            else:  # not being pressed
                pass

    clock_cur, _ = fetch_time()
    if clock_cur != clock_state['time']:
        update_display = True
        clock_state['time'] = clock_cur

    if clock_state['display'] == 'home' and time.time() - time_prev > tau_spotify:
        time_prev = time.time()
        api_info, spotify_state = fetch_spotify(api_info)
        if spotify_state['is_playing']:
            update_display = True

    # TODO clean this up
    if update_display:
        update_display = False
        if(clock_state['display'] == 'home'):
            display_time(spotify_state, clock_state['color'])
        elif(clock_state['display'] == 'network'):
            display_network(clock_state['net_info'], clock_state['color'])
        elif(clock_state['display'] == 'custom'):
            display_custom('fetching data...', clock_state['color'])

    time.sleep(0.01)
