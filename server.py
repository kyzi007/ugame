# -*- coding:utf-8 -*-
import json
import random

import time
import redis
import asyncio_redis

from aiohttp import web
from aiohttp_session import get_session, setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import config

routes = web.RouteTableDef()


def get_redis():
    pool = redis.ConnectionPool(host='localhost', port=6379)
    return redis.Redis(connection_pool=pool)


def generate_bots(count, map_size):
    bots = random.sample(range(0, map_size * map_size), count)
    db = get_redis()
    db.sadd('cells', *bots)


def take_free_cell(map_size):
    db = get_redis()
    cells_total = map_size * map_size

    players_count = db.scard('cell')
    if players_count > cells_total / 4:
        return -1

    while True:
        cell = random.randint(0, cells_total)
        exist = db.sismember('cells', cell)

        if not exist:
            db.sadd('cells', cell)
            return cell


def get_map_area(center_point, area_map_size, map_size):
    db = get_redis()
    cells = db.smembers('cells')
    cells = map(lambda x: int(x), cells)

    # area left top cell
    start = center_point - map_size * int(area_map_size / 2)
    start -= int(area_map_size / 2)
    start = max(0, start)

    view_cells = []
    for i in range(0, area_map_size):
        view_cells += filter(lambda x: start + map_size * i <= x < start + map_size * i + area_map_size, cells)

    return view_cells, start



def to_xy(cell: int, map_size: int):
    y = int(cell / map_size)
    x = cell - map_size * y
    return x, y


@routes.get('/game')
async def game(request):
    session = await get_session(request)

    if session.new:
        session['cell'] = take_free_cell(config.MAP_SIZE)

    if session['cell'] == -1:
        response_data = {'error': 'no free cells'}
    else:
        cells, start = get_map_area(
            center_point=session['cell'],
            area_map_size=config.VISIBLE_MAP_SIZE,
            map_size=config.MAP_SIZE)

        response_data = {
            'cell': to_xy(session['cell'], config.MAP_SIZE),
            'map': list(map(lambda cell: to_xy(cell, config.MAP_SIZE), cells)),
            'map_start': to_xy(start, config.MAP_SIZE),
            'view_width': config.VISIBLE_MAP_SIZE,
            'view_height': config.VISIBLE_MAP_SIZE,
            'map_width': config.MAP_SIZE,
            'map_height': config.MAP_SIZE
        }

    return web.Response(body=json.dumps(response_data))


class Game(web.Application):
    async def startup(self) -> None:
        db = get_redis()
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
