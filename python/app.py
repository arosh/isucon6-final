# -*- coding: utf-8 -*-
import ujson as json
import os
from datetime import timedelta, tzinfo
import time
import redis
import pickle

import MySQLdb.cursors

from flask import Flask, jsonify, request, Response

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_POOL = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0)


def get_redis():
    return redis.StrictRedis(connection_pool=REDIS_POOL)

_db = None

def get_db():
    global _db
    if _db is None:
        host = os.environ.get('MYSQL_HOST', 'localhost')
        port = int(os.environ.get('MYSQL_PORT', 3306))
        user = os.environ.get('MYSQL_USER', 'root')
        passwd = os.environ.get('MYSQL_PASS', '')
        dbname = 'isuketch'
        charset = 'utf8mb4'
        cursorclass = MySQLdb.cursors.DictCursor
        autocommit = True
        _db = MySQLdb.connect(host=host, port=port, user=user, passwd=passwd, db=dbname, cursorclass=cursorclass, charset=charset, autocommit=autocommit)
    return _db


def execute(db, sql, params={}):
    cursor = db.cursor()
    cursor.execute(sql, params)
    return cursor.lastrowid


def select_one(db, sql, params={}):
    cursor = db.cursor()
    cursor.execute(sql, params)
    return cursor.fetchone()


def select_all(db, sql, params={}):
    cursor = db.cursor()
    cursor.execute(sql, params)
    return cursor.fetchall()


def print_and_flush(content):
    return content


def type_cast_point_data(data):
    return {
        'id': int(data['id']),
        'stroke_id': int(data['stroke_id']),
        'x': float(data['x']),
        'y': float(data['y']),
    }


class UTC(tzinfo):
    def utcoffset(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return timedelta(0)


def to_RFC3339_micro(date):
    # RFC3339では+00:00のときはZにするという仕様だが、pythonは準拠していないため
    return date.replace(tzinfo=UTC()).isoformat().replace('+00:00', 'Z')


def type_cast_stroke_data(data):
    return {
        'id': int(data['id']),
        'room_id': int(data['room_id']),
        'width': int(data['width']),
        'red': int(data['red']),
        'green': int(data['green']),
        'blue': int(data['blue']),
        'alpha': float(data['alpha']),
        'points': list(map(type_cast_point_data, data['points'])) if 'points' in data and data['points'] else [],
        'created_at': to_RFC3339_micro(data['created_at']) if data['created_at'] else '',
    }


def type_cast_room_data(data):
    return {
        'id': int(data['id']),
        'name': data['name'],
        'canvas_width': int(data['canvas_width']),
        'canvas_height': int(data['canvas_height']),
        'created_at': to_RFC3339_micro(data['created_at']) if data['created_at'] else '',
        'strokes': list(map(type_cast_stroke_data, data['strokes'])) if 'strokes' in data and data['strokes'] else [],
        'stroke_count': int(data.get('stroke_count', 0)),
        'watcher_count': int(data.get('watcher_count', 0)),
    }


class TokenException(Exception):
    pass


def check_token(db, csrf_token):
    sql = 'SELECT `id`, `csrf_token`, `created_at` FROM `tokens`'
    sql += ' WHERE `csrf_token` = %(csrf_token)s AND `created_at` > CURRENT_TIMESTAMP(6) - INTERVAL 1 DAY'
    token = select_one(db, sql, {'csrf_token': csrf_token})
    if not token:
        raise TokenException()
    return token


def get_stroke_points(db, stroke_id):
    sql = 'SELECT `id`, `stroke_id`, `x`, `y` FROM `points` WHERE `stroke_id` = %(stroke_id)s ORDER BY `id` ASC'
    return select_all(db, sql, {'stroke_id': stroke_id})


def get_strokes(db, room_id, greater_than_id):
    sql = 'SELECT `id`, `room_id`, `width`, `red`, `green`, `blue`, `alpha`, `created_at` FROM `strokes`'
    sql += ' WHERE `room_id` = %(room_id)s AND `id` > %(greater_than_id)s ORDER BY `id` ASC'
    return select_all(db, sql, {'room_id': room_id, 'greater_than_id': greater_than_id})


def get_room(db, room_id):
    sql = 'SELECT `id`, `name`, `canvas_width`, `canvas_height`, `created_at` FROM `rooms` WHERE `id` = %(room_id)s'
    return select_one(db, sql, {'room_id': room_id})


def get_watcher_count(db, room_id):
    sql = 'SELECT COUNT(*) AS `watcher_count` FROM `room_watchers`'
    sql += ' WHERE `room_id` = %(room_id)s AND `updated_at` > CURRENT_TIMESTAMP(6) - INTERVAL 3 SECOND'
    result = select_one(db, sql, {'room_id': room_id})
    return result['watcher_count']


def update_room_watcher(db, room_id, token_id):
    sql = 'INSERT INTO `room_watchers` (`room_id`, `token_id`) VALUES (%(room_id)s, %(token_id)s)'
    sql += ' ON DUPLICATE KEY UPDATE `updated_at` = CURRENT_TIMESTAMP(6)'
    return execute(db, sql, {'room_id': room_id, 'token_id': token_id})


app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['DEBUG'] = os.environ.get('ISUCON_ENV') != 'production'

# Routes


@app.route('/api/csrf_token', methods=['POST'])
def post_api_csrf_token():
    db = get_db()

    sql = 'INSERT INTO `tokens` (`csrf_token`) VALUES'
    sql += ' (SHA2(CONCAT(RAND(), UUID_SHORT()), 256))'

    id = execute(db, sql)

    sql = 'SELECT `id`, `csrf_token`, `created_at` FROM `tokens` WHERE id = %(id)s'
    token = select_one(db, sql, {'id': id})

    return jsonify({'token': token['csrf_token']})


@app.route('/api/rooms', methods=['GET'])
def get_api_rooms():
    r = get_redis()
    rooms = r.get('rooms')

    if rooms is not None:
        rooms = pickle.loads(rooms)
    else:
        db = get_db()
        sql = '''
        SELECT
            strokes.room_id AS room_id,
            rooms.name AS room_name,
            rooms.canvas_width AS room_canvas_width,
            rooms.canvas_height AS room_canvas_height,
            rooms.created_at AS room_created_at,
            MAX(strokes.id) AS max_id,
            (SELECT COUNT(*) FROM strokes AS s WHERE s.room_id = strokes.room_id) AS stroke_count
        FROM strokes
        JOIN rooms ON rooms.id = strokes.room_id
        GROUP BY strokes.room_id
        ORDER BY max_id DESC LIMIT 100;
        '''
        results = select_all(db, sql)

        rooms = []
        for result in results:
            room = {}
            room['id'] = result['room_id']
            room['name'] = result['room_name']
            room['canvas_width'] = result['room_canvas_width']
            room['canvas_height'] = result['room_canvas_height']
            room['created_at'] = result['room_created_at']
            room['stroke_count'] = result['stroke_count']
            rooms.append(room)
        rooms = list(map(type_cast_room_data, rooms))
        r.set('rooms', pickle.dumps(rooms, -1))

    return jsonify({'rooms': rooms})


@app.route('/api/rooms', methods=['POST'])
def post_api_rooms():
    db = get_db()
    try:
        token = check_token(db, request.headers.get('x-csrf-token'))
    except TokenException:
        res = jsonify({'error': 'トークンエラー。ページを再読み込みしてください。'})
        res.status_code = 400
        return res

    posted_room = request.get_json()
    if 'name' not in posted_room or 'canvas_width' not in posted_room or 'canvas_height' not in posted_room:
        res = jsonify({'error': 'リクエストが正しくありません。'})
        res.status_code = 400
        return res

    cursor = db.cursor()
    cursor.connection.autocommit(False)
    try:
        sql = 'INSERT INTO `rooms` (`name`, `canvas_width`, `canvas_height`)'
        sql += ' VALUES (%(name)s, %(canvas_width)s, %(canvas_height)s)'
        cursor.execute(sql, {
            'name': posted_room.get('name'),
            'canvas_width': posted_room.get('canvas_width'),
            'canvas_height': posted_room.get('canvas_height'),
        })
        room_id = cursor.lastrowid

        sql = 'INSERT INTO `room_owners` (`room_id`, `token_id`) VALUES (%(room_id)s, %(token_id)s)'
        cursor.execute(sql, {
            'room_id': room_id,
            'token_id': token['id'],
        })
        cursor.connection.commit()
        r = get_redis()
        r.delete('rooms')
        r.delete('/')
    except Exception as e:
        cursor.connection.rollback()
        app.logger.error(e)
        res = jsonify({'error': 'エラーが発生しました。'})
        res.status_code = 500
        return res
    else:
        cursor.connection.autocommit(True)

    room = get_room(db, room_id)
    return jsonify({'room': type_cast_room_data(room)})

def get_strokes_with_points(db, room_id, greater_than_id):
    sql = '''
    SELECT
        `points`.`id` AS `id`,
        `points`.`stroke_id` AS `stroke_id`,
        `points`.`x` AS `x`,
        `points`.`y` AS `y`
    FROM `strokes`
    JOIN `points` ON `points`.`stroke_id` = `strokes`.`id`
    WHERE `strokes`.`room_id` = %(room_id)s AND `strokes`.`id` > %(greater_than_id)s
    ORDER BY `points`.`id` ASC'''
    return select_all(db, sql, {'room_id': room_id, 'greater_than_id': greater_than_id})


@app.route('/api/rooms/<id>')
def get_api_rooms_id(id):
    db = get_db()
    room = get_room(db, id)

    if room is None:
        res = jsonify({'error': 'この部屋は存在しません。'})
        res.status_code = 500
        return res

    room['watcher_count'] = get_watcher_count(db, room['id'])
    r = get_redis()
    strokes = r.get('stroke:%d' % room['id'])
    if strokes is not None:
        room['strokes'] = pickle.loads(strokes)
        res = type_cast_room_data(room)
    else:
        strokes = get_strokes(db, room['id'], 0)
        points_all = get_strokes_with_points(db, room['id'], 0)
        points = {}
        for point in points_all:
            stroke_id = point['stroke_id']
            points.setdefault(stroke_id, [])
            points[stroke_id].append(point)

        for stroke in strokes:
            stroke['points'] = points[stroke['id']]

        r.set('stroke:%d' % room['id'], pickle.dumps(strokes, -1))
        room['strokes'] = strokes
        res = type_cast_room_data(room)
    return jsonify({'room': res})


@app.route('/api/stream/rooms/<id>')
def get_api_stream_rooms_id(id):
    db = get_db()

    try:
        token = check_token(db, request.args.get('csrf_token'))
    except TokenException:
        return print_and_flush(
            'event:bad_request\n' +
            'data:トークンエラー。ページを再読み込みしてください。\n\n'
        ), 200, {'Content-Type': 'text/event-stream'}

    room = get_room(db, id)

    if room is None:
        return print_and_flush(
            'event:bad_request\n' +
            'data:この部屋は存在しません\n\n'
        ), 200, {'Content-Type': 'text/event-stream'}

    last_stroke_id = 0
    if 'Last-Event-ID' in request.headers:
        last_stroke_id = request.headers.get('Last-Event-ID')

    def gen(db, room, token, last_stroke_id):
        update_room_watcher(db, room['id'], token['id'])
        watcher_count = get_watcher_count(db, room['id'])

        yield print_and_flush(
            'retry:500\n\n' +
            'event:watcher_count\n' +
            'data:%d\n\n' % (watcher_count)
        )

        strokes = get_strokes(db, room['id'], last_stroke_id)
        points_all = get_strokes_with_points(db, room['id'], last_stroke_id)
        points = {}
        for point in points_all:
            stroke_id = point['stroke_id']
            points.setdefault(stroke_id, [])
            points[stroke_id].append(point)

        for stroke in strokes:
            stroke['points'] = points[stroke['id']]
            yield print_and_flush(
                'id:' + str(stroke['id']) + '\n\n' +
                'event:stroke\n' +
                'data:' + json.dumps(type_cast_stroke_data(stroke)) + '\n\n'
            )

    return Response(gen(db, room, token, last_stroke_id), mimetype='text/event-stream')


@app.route('/api/strokes/rooms/<id>', methods=['POST'])
def post_api_strokes_rooms_id(id):
    db = get_db()

    try:
        token = check_token(db, request.headers.get('x-csrf-token'))
    except TokenException:
        res = jsonify({'error': 'トークンエラー。ページを再読み込みしてください。'})
        res.status_code = 400
        return res

    room = get_room(db, id)

    if room is None:
        res = jsonify({'error': 'この部屋は存在しません。'})
        res.status_code = 404
        return res

    posted_stroke = request.get_json()
    if 'width' not in posted_stroke or 'points' not in posted_stroke:
        res = jsonify({'error': 'リクエストが正しくありません。'})
        res.status_code = 400
        return res

    strokes = get_strokes(db, room['id'], 0)
    if len(strokes) == 0:
        sql = 'SELECT COUNT(*) AS cnt FROM `room_owners` WHERE `room_id` = %(room_id)s AND `token_id` = %(token_id)s'
        result = select_one(db, sql, {'room_id': room['id'], 'token_id': token['id']})
        if result['cnt'] == 0:
            res = jsonify({'error': '他人の作成した部屋に1画目を描くことはできません'})
            res.status_code = 400
            return res

    cursor = db.cursor()
    cursor.connection.autocommit(False)
    try:
        sql = 'INSERT INTO `strokes` (`room_id`, `width`, `red`, `green`, `blue`, `alpha`)'
        sql += ' VALUES(%(room_id)s, %(width)s, %(red)s, %(green)s, %(blue)s, %(alpha)s)'
        cursor.execute(sql, {
            'room_id': room['id'],
            'width': posted_stroke.get('width'),
            'red': posted_stroke.get('red'),
            'green': posted_stroke.get('green'),
            'blue': posted_stroke.get('blue'),
            'alpha': posted_stroke.get('alpha'),
        })
        stroke_id = cursor.lastrowid

        sql = 'INSERT INTO `points` (`stroke_id`, `x`, `y`) VALUES (%(stroke_id)s, %(x)s, %(y)s)'
        for point in posted_stroke.get('points'):
            cursor.execute(sql, {
                'stroke_id': stroke_id,
                'x': point['x'],
                'y': point['y']
            })
        cursor.connection.commit()
        filename = '../react/img/' + id + '.svg'
        if os.path.exists(filename):
            os.remove(filename)
        
        r = get_redis()
        r.delete('stroke:%d' % room['id'], 'rooms', '/', '/rooms/%d' % room['id'])
    except Exception as e:
        cursor.connection.rollback()
        app.logger.error(e)
        res = jsonify({'error': 'エラーが発生しました。'})
        res.status_code = 500
        return res
    else:
        cursor.connection.autocommit(True)

    sql = 'SELECT `id`, `room_id`, `width`, `red`, `green`, `blue`, `alpha`, `created_at` FROM `strokes`'
    sql += ' WHERE `id` = %(stroke_id)s'
    stroke = select_one(db, sql, {'stroke_id': stroke_id})

    stroke['points'] = get_stroke_points(db, stroke_id)

    return jsonify({'stroke': type_cast_stroke_data(stroke)})

#from wsgi_lineprof.filters import FilenameFilter, TotalTimeSorter, TopItemsFilter
#from wsgi_lineprof.middleware import LineProfilerMiddleware
#filters = [
#    FilenameFilter("/home/isucon/webapp/python/app.py"), # Flaskのファイル名にも app.py が含まれていて若干邪魔なのでなんとかしたい
#    TotalTimeSorter(),
#    TopItemsFilter(n=20),
#]
#f = open("lineprof.log", "w")
#app.wsgi_app = LineProfilerMiddleware(app.wsgi_app, filters=filters, stream=f)

#from werkzeug.contrib.profiler import ProfilerMiddleware
#app.wsgi_app = ProfilerMiddleware(app.wsgi_app, profile_dir="/tmp/profile")

if __name__ == '__main__':
    debug = os.environ.get('ISUCON_ENV') != 'production'
    app.run(host='', port=8000)
