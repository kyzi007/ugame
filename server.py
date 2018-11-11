# -*- coding:utf-8 -*-
import json
import random

import redis

from aiohttp import web
from aiohttp_session import get_session, setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import config

routes = web.RouteTableDef()


def get_redis_from_pool():
    pool = redis.ConnectionPool(host='localhost', port=6379)
    return redis.Redis(connection_pool=pool)


def to_xy(cell: int, map_size: int):
    y = int(cell / map_size)
    x = cell - map_size * y
    return x, y


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
            db.append(key, value)


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


def cut_map_area(all_cells, center_point, area_map_size, map_size):
    view_cells = []
    all_cells = map(lambda x: int(x), all_cells)

    # area left top cell
    start = center_point - map_size * int(area_map_size / 2)
    start -= int(area_map_size / 2)
    start = max(0, start)

    all_cells = list(all_cells)
    for i in range(0, area_map_size):
        start_ = start + map_size * i
        view_cells += filter(lambda x: start_ <= x < start_ + area_map_size, all_cells)

    return view_cells, start


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

        # generate random info
        player_info = generate_player_info(cell)
        for key, value in player_info.items():
            db.append(key, value)
    else:
        cell = session['cell']

    all_cells = db.smembers('cells')

    cells, start = cut_map_area(
        all_cells=all_cells,
        center_point=cell,
        area_map_size=config.VISIBLE_MAP_SIZE,
        map_size=config.MAP_SIZE)
    map_info = []

    # gets bots and other players info
    for uid in cells:
        map_info.append(
            {
                # todo tasks
                'name': db.get('player:%s:name' % uid),
                'type': db.get('player:%s:type' % uid),
                'uid': uid,
                'coord': to_xy(uid)
            }
        )

    response_data = {
        # i don`t hate frontend developers
        'player_uid': cells,
        'player_coord': to_xy(cell, config.MAP_SIZE),
        'map': list(map(lambda x: to_xy(x, config.MAP_SIZE), cells)),
        'map_start': to_xy(start, config.MAP_SIZE),
        'view_width': config.VISIBLE_MAP_SIZE,
        'view_height': config.VISIBLE_MAP_SIZE,
        'map_width': config.MAP_SIZE,
        'map_height': config.MAP_SIZE
    }

    return web.Response(body=json.dumps(response_data))


class Game(web.Application):
    async def startup(self) -> None:
        db = get_redis_from_pool()
        db.flushdb()
        generate_bots(config.BOTS_COUNT, config.MAP_SIZE)
        await self.on_startup.send(self)


@routes.get('/index')
async def index(request):
    return web.FileResponse('./index.html')


if __name__ == '__main__':
    app = Game()
    app.add_routes(routes)

    setup(app, EncryptedCookieStorage(config.SECRET))

    web.run_app(app, port=8888)
