# -*- coding:utf-8 -*-
import json
import random
import asyncio

import asyncio_redis
from aiohttp import web
from aiohttp_session import get_session, setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage

import config

routes = web.RouteTableDef()
redis = asyncio_redis.Connection.create(host='127.0.0.1', port=6379)


@asyncio.coroutine
async def generate_fake_users():
    pass


# все ключи редиса в коллекции - активные игроки
@routes.get('/game')
async def register_user(request):
    i = random.random()
    print('start %s' % i)

    session = await get_session(request)
    if session.new:
        # алгоритм поиска другой клетки если занята случайная
        session['x'] = random.randint(config.MIN_X, config.MAX_X)
        session['y'] = random.randint(config.MIN_Y, config.MAX_Y)

    response_data = {'x': session['x'], 'y': session['y']}

    print('end %s' % i)
    return web.Response(body=json.dumps(response_data))


@routes.get('/index')
async def index(request):
    return web.FileResponse('./index.html')


app = web.Application()
app.add_routes(routes)

setup(app, EncryptedCookieStorage(config.SECRET))

web.run_app(app, port=8888)
