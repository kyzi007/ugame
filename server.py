# -*- coding:utf-8 -*-
import json
import random
import datetime

import re
import redis
import asyncio_redis

from aiohttp import web
from aiohttp_session import get_session, setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import config

routes = web.RouteTableDef()


def get_redis_from_pool():
    pool = redis.ConnectionPool(host='localhost', port=6379)
    return redis.Redis(connection_pool=pool)


async def get_async_redis():
    return await asyncio_redis.Connection.create(host='127.0.0.1', port=6379)


def to_xy(cell, map_size):
    y = int(cell / map_size)
    x = cell - map_size * y
    return [x, y]


def from_xy(x, y, map_size):
    return y * map_size + x


def generate_bot_info(uid):
    return {
        'player:%s:type' % uid: 'bot',
        'player:%s:name' % uid: 'Bot %s' % random.choice(config.NAMES)
    }


def generate_player_info(uid):
    return {
        'player:%s:type' % uid: 'player',
        'player:%s:name' % uid: 'Player %s' % random.choice(config.NAMES)
    }


def generate_bots(db, total, map_size):
    """
    Create and save bots
    """
    bots = random.sample(range(0, map_size * map_size), total)
    db.sadd('cells', *bots)
    for uid in bots:
        info = generate_bot_info(uid)
        for key, value in info.items():
            db.set(key, value)


def search_free_cell(db, map_size):
    """
    Search free cell for player
    """
    cells_total = map_size * map_size

    players_count = db.scard('cell')
    # limit players in map
    if players_count > cells_total / 2:
        return -1

    while True:
        cell = random.randint(0, cells_total)
        exist = db.sismember('cells', cell)

        if not exist:
            return cell


def cut_map_area(start, all_cells, area_map_size, map_size):
    view_cells = []
    all_cells = map(lambda x: int(x), all_cells)

    # area left top cell
    all_cells = list(all_cells)
    for i in range(0, area_map_size):
        start_ = start + map_size * i
        view_cells += filter(lambda x: start_ <= x < start_ + area_map_size, all_cells)

    return view_cells


@routes.get('/spawn_tasks')
async def spawn_tasks(request):
    db = await get_async_redis()
    i = config.BOTS_COUNT * 4
    while i > 0:
        i -= 1

        random_key = await db.randomkey()
        if 'player' in random_key:
            uid = random_key.split(':')[1]
            tasks = await db.keys('task:%s:*' % uid)
            tasks = list(tasks)
            if len(tasks) < 4:
                task_id = random.choice(list(set(range(0, 4)) - set(map(lambda x: x.result().split(':')[2], tasks))))
                expire = random.randint(10, 10 * 60)
                now = datetime.datetime.now().strftime('%H:%M:%S')
                await db.set('task:%s:%s' % (uid, task_id), '%s-%s' % (now, expire), expire=expire)


@routes.get('/info')
async def tasks(request):
    db = get_redis_from_pool()

    x = request.query['x']
    y = request.query['y']
    cell = from_xy(int(x), int(y), config.MAP_SIZE)

    response_data = {
        'name': db.get('player:%s:name' % cell).decode(),
        'tasks': []
    }
    tasks_keys = db.keys('task:%s:*' % cell)
    for key in tasks_keys:
        task_name = 'Task %s' % key.decode().split(':')[2]
        time_data = db.get(key).decode()
        now = datetime.datetime.now()
        h, m, s, expire = re.findall('(\d+):(\d+):(\d+)-(\d+)', time_data)[0]
        created = now.replace(hour=int(h), minute=int(m), second=int(s))
        time_to_end = int(expire) - (now - created).seconds
        m = int(time_to_end / 60)
        s = time_to_end - m * 60
        response_data['tasks'].append([task_name, created.strftime('%H:%M:%S'), '%smin %ss' % (m, s)])

    return web.Response(body=json.dumps(response_data))


@routes.get('/move')
async def move(request):
    # not async redis a lot faster
    # one point to db access
    db = get_redis_from_pool()

    session = await get_session(request)
    direction = request.query['direction']

    # todo validate
    x, y = to_xy(session['map_position'], config.MAP_SIZE)
    if direction == 'top':
        y -= config.MOVE_SPEED
        y = max(0, y)
    elif direction == 'bottom':
        y += config.MOVE_SPEED
        y = min(y, config.MAP_SIZE - config.MOVE_SPEED)
    elif direction == 'left':
        x -= config.MOVE_SPEED
        x = max(0, x)
    elif direction == 'right':
        x += config.MOVE_SPEED
        x = min(x, config.MAP_SIZE - config.MOVE_SPEED)
    elif direction == 'self':
        x, y = to_xy(session['cell'], config.MAP_SIZE)
        x -= int(config.VISIBLE_MAP_SIZE / 2)
        x = min(x, config.MAP_SIZE - int(config.VISIBLE_MAP_SIZE / 2))
        y -= int(config.VISIBLE_MAP_SIZE / 2)
        y = min(y, config.MAP_SIZE - int(config.VISIBLE_MAP_SIZE / 2))
    elif direction == 'cell':
        x = int(request.query['x'])
        y = int(request.query['y'])

    session['map_position'] = from_xy(x, y, config.MAP_SIZE)
    response_data = await get_map(db, session)

    return web.Response(body=json.dumps(response_data))


@routes.get('/game')
async def game(request):
    """
    init and save player, save player uid into session and return map
    """
    session = await get_session(request)
    # not async redis a lot faster
    # one point to db access
    db = get_redis_from_pool()

    if session.new:
        cell = session['cell'] = search_free_cell(db, config.MAP_SIZE)
        if cell == -1:
            response_data = {'error': 'no free cells'}
            return web.Response(body=json.dumps(response_data))

        db.sadd('cells', cell)

        # player to view zone center
        map_position = cell - config.MAP_SIZE * int(config.VISIBLE_MAP_SIZE / 2)
        map_position -= int(config.VISIBLE_MAP_SIZE / 2)
        map_position = max(0, map_position)

        session['map_position'] = map_position

        # generate random info
        player_info = generate_player_info(cell)
        for key, value in player_info.items():
            db.set(key, value)

    response_data = await get_map(db, session)
    return web.Response(body=json.dumps(response_data))


async def get_map(db, session):
    all_cells = db.smembers('cells')
    cells = cut_map_area(
        start=session['map_position'],
        all_cells=all_cells,
        area_map_size=config.VISIBLE_MAP_SIZE,
        map_size=config.MAP_SIZE)
    map_info = []

    # gets bots and other players info
    for uid in cells:
        map_info.append({
            'type': db.get('player:%s:type' % uid).decode(),
            'uid': uid,
            'coord': to_xy(uid, config.MAP_SIZE)
        })
    response_data = {
        # i don`t hate frontend developers
        'player_uid': session['cell'],
        'map': map_info,
        'map_position': to_xy(session['map_position'], config.MAP_SIZE),
        'view_width': config.VISIBLE_MAP_SIZE,
        'view_height': config.VISIBLE_MAP_SIZE,
        'map_width': config.MAP_SIZE,
        'map_height': config.MAP_SIZE
    }

    return response_data


class Game(web.Application):
    async def startup(self) -> None:
        # db = get_redis_from_pool()
        # db.flushdb()
        # generate_bots(db, config.BOTS_COUNT, config.MAP_SIZE)
        await self.on_startup.send(self)


@routes.get('/index')
async def index(request):
    return web.FileResponse('./index.html')


if __name__ == '__main__':
    app = Game()
    app.add_routes(routes)

    setup(app, EncryptedCookieStorage(config.SECRET))

    web.run_app(app, port=8888)
