#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import shutil
import uuid
from collections import defaultdict

import googlemaps
from googlemaps.distance_matrix import distance_matrix
from telebot import TeleBot
from telebot import types

from db import db, User, Place, DoesNotExist
from settings import TOKEN, API_KEY

START, ADDRESS, PHOTO, LOCATION, NEAREST = range(5)
USER_STATE = defaultdict(lambda: START)
PLACES = defaultdict(lambda: {})
bot = TeleBot(TOKEN)


def get_state(message):
    return USER_STATE[message.chat.id]


def update_state(message, state):
    USER_STATE[message.chat.id] = state


def get_place(message):
    return PLACES[message.chat.id]


def update_place(message, key, value):
    PLACES[message.chat.id][key] = value


def save_place(message):
    place = get_place(message)
    download_photo = bot.download_file(place.get('photo_path'))
    photo_user_folder = 'user_{}'.format(str(message.chat.id))
    photo_file_name = '{}.jpg'.format(str(uuid.uuid4()))
    os.makedirs(photo_user_folder, exist_ok=True)
    photo_path = os.path.join(photo_user_folder, photo_file_name)
    with open(photo_path, 'wb') as p:
        p.write(download_photo)
    try:
        user = User.get(User.user_id == message.chat.id)
    except DoesNotExist:
        with db.atomic():
            user = User.create(user_id=message.chat.id)
    with db.atomic():
        Place.create(user=user, name=place.get('name'), photo=photo_path,
                     location=place.get('location'))
    db.close()
    bot.send_message(message.chat.id, 'Ок, место сохранено.')


@bot.message_handler(commands=['start', 'help'], func=lambda message: get_state(message) == START)
def send_welcome(message):
    bot.send_message(message.chat.id, 'Список доступных команд:\n'
                                      '/add - добавить новое место\n'
                                      '/list - отобразить добавленные места\n'
                                      '/nearest - отобразить места рядом с вами\n'
                                      '/reset - удалить все добавленные локации\n'
                                      '/help - отобразить список доступных команд')


@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    bot.send_message(message.chat.id, 'Добавление места отменено.')
    update_state(message, START)


@bot.message_handler(commands=['add'])
def send_address(message):
    bot.send_message(message.chat.id, 'Отправьте название места или введите /cancel чтобы отменить добавление.')
    update_state(message, ADDRESS)


@bot.message_handler(func=lambda message: get_state(message) == ADDRESS)
def handle_address(message):
    if re.search(r'[a-zа-я]', message.text, re.IGNORECASE):
        update_place(message, 'name', message.text)
        bot.send_message(message.chat.id, 'Теперь отправьте фото места или введите /cancel чтобы отменить добавление.')
        update_state(message, PHOTO)
    else:
        bot.send_message(message.chat.id, 'Отправьте корректный адрес места!')


@bot.message_handler(func=lambda message: get_state(message) == PHOTO, content_types=['photo'])
def handle_photo(message):
    fileID = message.photo[-1].file_id
    update_place(message, 'photo_path', bot.get_file(fileID).file_path)
    bot.send_message(message.chat.id,
                     'Теперь отправьте координаты'
                     ' (например: 58.391693, 26.359372) или геопозицию места'
                     ' или введите /cancel чтобы отменить добавление.')
    update_state(message, LOCATION)


@bot.message_handler(func=lambda message: get_state(message) == LOCATION, content_types=['text', 'location'])
def handle_location(message):
    if message.text:
        if re.search(r'\d+\.\d+,\s\d+\.\d+', message.text):
            update_place(message, 'location', message.text)
            save_place(message)
            update_state(message, START)
        else:
            bot.send_message(message.chat.id, 'Отправьте корректные координаты! Например: 58.391693, 26.359372.')
    elif message.location:
        update_place(message, 'location', '{}, {}'.format(message.location.latitude, message.location.longitude))
        save_place(message)
        update_state(message, START)


@bot.message_handler(commands=['list'])
def list_command(message):
    try:
        user = User.get(User.user_id == message.chat.id)
        places = user.places.order_by(Place.upload_date.desc()).limit(10)
        for place in places:
            with open(place.photo, 'rb') as photo:
                bot.send_photo(message.chat.id, photo=photo,
                               caption='{}'.format(place.name))
                location = place.location.replace(' ', '').split(',')
                bot.send_location(message.chat.id, latitude=location[0], longitude=location[1])
    except DoesNotExist:
        bot.send_message(message.chat.id,
                         'У вас нет сохраненных мест. Используйте команду /add чтобы добавить новое место.')
    db.close()


@bot.message_handler(commands=['nearest'])
def nearest_command(message):
    try:
        User.get(User.user_id == message.chat.id)
        bot.send_message(message.chat.id, 'Отправьте свою геопозицию или введите /cancel чтобы отменить.')
        update_state(message, NEAREST)
    except DoesNotExist:
        bot.send_message(message.chat.id,
                         'У вас нет сохраненных мест. Используйте команду /add чтобы добавить новое место.')


@bot.message_handler(func=lambda message: get_state(message) == NEAREST, content_types=['location'])
def handle_nearest(message):
    g_maps = googlemaps.Client(key=API_KEY)
    latitude = message.location.latitude
    longitude = message.location.longitude
    send_no_places_message = False
    error_message = False
    start_message = bot.send_message(message.chat.id, 'Ищем места рядом с вами...')
    user = User.get(User.user_id == message.chat.id)
    for place in user.places:
        location = place.location.replace(' ', '').split(',')
        distance = distance_matrix(client=g_maps, origins={"lat": latitude, "lng": longitude},
                                   destinations={"lat": location[0], "lng": location[1]})
        print(distance)
        if distance.get('status') == 'OK':
            try:
                elements = distance.get('rows')[0].get('elements')[0]
                if elements.get('status') == 'OK':
                    error_message = False
                    distance = elements.get('distance').get('text')
                    if 'km' in distance:
                        distance = distance.split(' ')[0].replace(',', '.')
                        if float(distance) <= 0.5:
                            bot.send_message(message.chat.id, place.name)
                            bot.send_location(message.chat.id, latitude=location[0], longitude=location[1])
                            send_no_places_message = False
                        else:
                            send_no_places_message = True
                    else:
                        bot.send_message(message.chat.id, place.name)
                        bot.send_location(message.chat.id, latitude=location[0], longitude=location[1])
                else:
                    send_no_places_message = True
            except (AttributeError, IndexError):
                bot.edit_message_text(text='Не удалось получить ближайшие места.', chat_id=message.chat.id,
                                      message_id=start_message.message_id)
        else:
            error_message = distance.get('status')
    if send_no_places_message:
        bot.edit_message_text(text='Поблизости нет ваших мест.', chat_id=message.chat.id,
                              message_id=start_message.message_id)
    if error_message:
        bot.edit_message_text(text='К сожалению что-то пошло не так. Ошибка: {}'.format(error_message),
                              chat_id=message.chat.id,
                              message_id=start_message.message_id)


def create_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    answers = ['Да', 'Нет']
    buttons = [types.InlineKeyboardButton(text=answer, callback_data=answer) for answer in answers]
    keyboard.add(*buttons)
    return keyboard


@bot.message_handler(commands=['reset'])
def reset_command(message):
    try:
        User.get(User.user_id == message.chat.id)
        keyboard = create_keyboard()
        bot.send_message(message.chat.id, 'Вы точно хотите удалить все ваши сохраненные места?', reply_markup=keyboard)
    except DoesNotExist:
        bot.send_message(message.chat.id,
                         'У вас нет сохраненных мест. Используйте команду /add чтобы добавить новое место.')
    db.close()


@bot.callback_query_handler(func=lambda x: True)
def confirm_reset_handler(callback_query):
    message = callback_query.message
    answer = callback_query.data
    if answer == 'Да':
        User.get(User.user_id == message.chat.id).delete_instance()
        bot.send_message(message.chat.id, 'Ваши сохраненные места удалены!')
        db.close()
        photo_user_folder = 'user_{}'.format(str(message.chat.id))
        shutil.rmtree(photo_user_folder, ignore_errors=True)
    update_state(message, START)


if __name__ == '__main__':
    bot.polling()
