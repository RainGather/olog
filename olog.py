#! python3
import os
import re
import sys
import time
import fire
import json
import shutil
import pathlib
import hashlib
import asyncio
import datetime
import requests
import websockets


class Olog:

    def __init__(self):
        self.olog_cfg_path = pathlib.Path(__file__).parent / 'olog.cfg'
        self.olog_cfg_st_mtime = 0
        self.olog_cfg = {}
        self.read_olog_config()
        self.last_wechat_send_time = 0
        self.scan_results = {}
        self.watch_exts = ['err', 'msg']
        self.msgs = []

    def sendmsg(self, title, content, type_):
        self.msgs.append({
            'title': title,
            'content': content,
            'type_': type_
        })
        return True

    async def wechat_send(self):
        while True:
            try:
                if len(self.msgs) > 0:
                    while time.time() - self.last_wechat_send_time < 10:
                        await asyncio.sleep(1)
                    self.last_wechat_send_time = time.time()
                    msg = self.msgs[0]
                    title = msg['title']
                    content = msg['content']
                    type_ = msg['type_']
                    URL = 'http://wxpusher.zjiecode.com/api/send/message'
                    data = {
                        'appToken': self.olog_cfg['token'],
                        'content': content,
                        'summary': '[Olog] ' + title,
                        'contentType': type_,  # 1 string, 2 html, 3 markdown
                        'uids': self.olog_cfg['uids']
                    }
                    r = requests.post(URL, json=data)
                    if r.ok:
                        del self.msgs[0]
            except Exception as e:
                print(e, file=sys.stderr)
            await asyncio.sleep(1)

    def add_auth(self, payload):
        nowtime = time.time()
        result = {
            'payload': payload,
            'timestamp': nowtime,
            'checksum': hashlib.sha256((payload + str(nowtime) + self.olog_cfg['token']).encode('utf-8')).hexdigest()
        }
        result = json.dumps(result)
        return result
    
    def fetch_auth(self, data):
        if isinstance(data, str) and '{' in data:
            data = json.loads(data)
            if abs(data.get('timestamp', 0) - time.time()) < 10:
                checksum = hashlib.sha256((data.get('payload') + str(data.get('timestamp', '')) + self.olog_cfg['token']).encode('utf-8')).hexdigest()
                if checksum == data.get('checksum', ''):
                    return data.get('payload', '')
                else:
                    print(f'[ERROR] fetch auth checksum error!', file=sys.stderr)
            else:
                print(f'[ERROR] fetch auth checksum timestamp timeout!', file=sys.stderr)
        else:
            print(f'[ERROR] fetch auth data is not json str', file=sys.stderr)
        return False
    
    def read_olog_config(self):
        if self.olog_cfg_st_mtime == self.olog_cfg_path.stat().st_mtime:
            return
        if self.olog_cfg_path.exists():
            with self.olog_cfg_path.open('r', encoding='utf-8') as fr:
                try:
                    self.olog_cfg = json.load(fr)
                except Exception as e:
                    print(e, file=sys.stderr)
                    print('[ERROR] olog.cfg config json load error. May not delete comments?', file=sys.stderr)
                    exit(2)
            if '#' in self.olog_cfg['device']:
                self.device, self.addr = self.olog_cfg['device'].split('#')
            else:
                self.device = self.olog_cfg['device']
                self.addr = 'Addr not assign'
            self.olog_cfg['svr_ip'] = self.olog_cfg.get('svr_ip', 'localhost')
            if not self.olog_cfg['svr_ip']:
                self.olog_cfg['svr_ip'] = 'localhost'
            self.olog_cfg['svr_port'] = self.olog_cfg.get('svr_port', 8765)
            self.ws_uri = f'ws://{self.olog_cfg["svr_ip"]}:{self.olog_cfg["svr_port"]}'
        else:
            ans = input(f'[ERROR] olog.cfg not found! gen configs?(y/n)')
            if ans.lower() in ['y', 'yes']:
                ologc_sample_path = pathlib.Path(__file__).parent / 'olog.cfg.sample'
                ologc_path = pathlib.Path(__file__).parent / 'olog.cfg'
                shutil.copy(ologc_sample_path, ologc_path)
                with self.olog_cfg_path.open('w', encoding='utf-8') as fw:
                    json.dump(self.olog_cfg, fw, sort_keys=True, indent=4, separators=(',', ':'))
                print(f'[NOTICE] Please edit {self.olog_cfg_path}')
            exit(2)
        self.olog_cfg_st_mtime = self.olog_cfg_path.stat().st_mtime


class OlogClient(Olog):

    def __init__(self):
        super().__init__()
        self.log_monitor = {}
        self.watch_sent_time = {}
        for log_dir in self.olog_cfg['log_dirs']:
            log_dir = pathlib.Path(log_dir)
            for p in log_dir.glob('**/*'):
                self.log_monitor[str(p.resolve())] = {
                    'size': p.stat().st_size,
                    'mtime': p.stat().st_mtime
                }

    def run(self):
        print('[BEGIN] running as client...')
        self.sendmsg(f'{self.device} running as client...', f'{self.device} running as client...\n\n---\n\n{self.addr}', 3)
        while True:
            try:
                asyncio.get_event_loop().run_until_complete(asyncio.gather(self.client(), self.watch(), self.wechat_send()))
                asyncio.get_event_loop().run_forever()
            except Exception as e:
                print(e, file=sys.stderr)
                time.sleep(10)

    async def watch(self):
        while True:
            try:
                self.read_olog_config()
                for log_dir in self.olog_cfg['log_dirs']:
                    log_dir = pathlib.Path(log_dir)
                    for p in log_dir.glob('**/*'):
                        ext = p.suffix.lower()[1:] 
                        task = re.findall('@(.*?)@', p.stem)
                        if len(task) > 0:
                            task = task[0]
                        else:
                            task = p.stem
                        if ext not in self.watch_exts:
                            continue
                        if str(p.resolve()) in self.log_monitor.keys() and \
                            self.log_monitor[str(p.resolve())]['mtime'] == p.stat().st_mtime and \
                            self.log_monitor[str(p.resolve())]['size'] == p.stat().st_size:
                            continue
                        elif time.time() - self.watch_sent_time.get(str(p.resolve()), 0) > 24 * 3600 and \
                                time.time() - p.stat().st_mtime < 3600 and \
                                    time.time() - self.watch_sent_time.get(task, 0) > 600:
                            await asyncio.sleep(10)
                            with p.open('r', encoding='utf-8') as fr:
                                log_detail = fr.read().strip()
                            if not log_detail:
                                continue
                            if len(log_detail) > 1050:
                                log_detail = log_detail[:500] + '...\n......\n...' + log_detail[-500:]
                            log_date = datetime.datetime.fromtimestamp(p.stat().st_mtime)
                            title = f'{ext.upper()}: {self.device} @ {task}'
                            report = f'''## log info

device: {self.device}
task: {task}
addr: {self.addr}
log path: {p.resolve()}
log time: {log_date.strftime("%Y-%m-%d %H:%M:%S")}
report time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## log detail
{log_detail}
'''
                            self.sendmsg(title, report, 3)
                            self.log_monitor[str(p.resolve())] = {
                                'size': p.stat().st_size,
                                'mtime': p.stat().st_mtime
                            }
                            self.watch_sent_time[str(p.resolve())] = time.time()
                            self.watch_sent_time[task] = time.time()
            except Exception as e:
                print(e, file=sys.stderr)
            await asyncio.sleep(5)

    def scan_logs(self):
        print(f'[{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] scan_logs')
        tasks = {}
        for log_dir in self.olog_cfg['log_dirs']:
            log_dir = pathlib.Path(log_dir)
            for p in log_dir.glob('**/*'):
                ext = p.suffix.lower()[1:] 
                if ext not in ['log', 'err', 'scanerr']:
                    continue
                file_date = datetime.datetime.fromtimestamp(p.stat().st_mtime)
                results = re.findall(r'@(.*?)@', p.stem)
                if results:
                    task = results[0]
                else:
                    task = p.stem
                if datetime.datetime.now() - file_date > datetime.timedelta(days=self.olog_cfg['log_keep_days']):
                    os.remove(p)
                elif datetime.datetime.now() - file_date < datetime.timedelta(days=1):
                    if ext == 'log':
                        state = 'ok'
                    elif ext in ['err', 'scanerr']:
                        state = 'err'
                    with p.open('r', encoding='utf-8') as fr:
                        detail = fr.read()
                        if len(detail) > 120:
                            detail = detail[:50] + '...\n......\n...' + detail[-50:]
                    tasks[task] = {
                        'state': state,
                        'logdate': file_date.strftime('%Y-%m-%d %H:%M:%S'),
                        'detail': detail
                    }
        return tasks

    async def client(self):
        while True:
            try:
                print(f'[NOTICE] connecting {self.ws_uri}')
                async with websockets.connect(self.ws_uri) as websocket:
                    payload = self.add_auth(self.olog_cfg['device'])
                    await websocket.send(payload)
                    print(f'[NOTICE] connected {self.ws_uri}')
                    while True:
                        recv = await websocket.recv()
                        recv = self.fetch_auth(recv)
                        if recv == 'report now':
                            report = self.scan_logs()
                            report = json.dumps(report)
                            payload = self.add_auth(report)
                            await websocket.send(payload)
                        elif recv == 'ping':
                            payload = self.add_auth('pong')
                            await websocket.send(payload)
            except Exception as e:
                print(e, file=sys.stderr)
                await asyncio.sleep(10)


class OlogSvr(Olog):

    def __init__(self):
        super().__init__()
        self.lock = asyncio.Lock()
        self.reports = {}
        self.last_report_time = datetime.datetime.now() - datetime.timedelta(days=1) + datetime.timedelta(minutes=2)
        self.last_scan_time = self.last_report_time - datetime.timedelta(minutes=1)

    def today_report_time(self, time):
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        today_time = datetime.datetime.strptime(f'{today}_{time}', '%Y-%m-%d_%H:%M')
        return today_time
    
    def device_offline(self, device):
        if '#' in device:
            device, addr = device.split('#')
        else:
            addr = 'Addr not assign'
        title = f'Device Offline: {device}'
        report = f'''# Device Offline: {device}

## {device} ssh addr
{addr}

## time
{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
'''
        print(f'[WARNING] device offline: {device}', file=sys.stderr)
        self.sendmsg(title, report, 3)
    
    async def ws_svr(self, websocket, path):
        async with self.lock:
            from_device = await websocket.recv()
        from_device = self.fetch_auth(from_device)
        if not from_device:
            return False
        if '#' in from_device:
            from_device_name, from_device_addr = from_device.split('#')
        else:
            from_device_name, from_device_addr = from_device, 'Addr not assign'
        print(f'[NOTICE] new device {from_device_name}')
        self.sendmsg(f'New Device Connected: {from_device_name}', f'New Device Connected: {from_device}', 3)
        while True:
            try:
                if self.reports.get(from_device, None) is None:
                    payload = self.add_auth('report now')
                    async with self.lock:
                        await websocket.send(payload)
                        recv = await websocket.recv()
                    recv = self.fetch_auth(recv)
                    if not recv:
                        return False
                    report = json.loads(recv)
                    self.reports[from_device] = report
                payload = self.add_auth('ping')
                async with self.lock:
                    await websocket.send(payload)
                    recv = await websocket.recv()
                recv = self.fetch_auth(recv)
                if not recv:
                    return False
                if recv != 'pong':
                    raise Exception(f'[ERROR] {from_device} ping pong error!')
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                self.device_offline(from_device)
                break
            except Exception as e:
                print(e, file=sys.stderr)
    
    async def gather_report(self):
        while True:
            try:
                if datetime.datetime.now() - self.last_scan_time >= datetime.timedelta(days=1):
                    print('reports init...')
                    self.reports = {}
                    self.last_scan_time = self.today_report_time(self.olog_cfg['report_time']) - datetime.timedelta(minutes=5)
                if datetime.datetime.now() - self.last_report_time >= datetime.timedelta(days=1):
                    title = f'Olog daily report [{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]'
                    html = self.gen_html(self.reports)
                    if self.olog_cfg.get('htmldir'):
                        htmlurl = self.save_html(html)
                        content = f'<a href="{htmlurl}">{htmlurl}</a>'
                        self.sendmsg(title, content, 2)
                        self.last_report_time = self.today_report_time(self.olog_cfg['report_time'])
                    else:
                        self.sendmsg(title, html, 2)
                        self.last_report_time = self.today_report_time(self.olog_cfg['report_time'])
                    await asyncio.sleep(60)
            except Exception as e:
                print(e, file=sys.stderr)
            await asyncio.sleep(1)
    
    def run(self):
        print('[BEGIN] running as websocket server...')
        self.sendmsg(f'{self.device} running as server...', f'{self.device} running as server...\n\n---\n\n{self.addr}\n\nNext report time: {(self.last_report_time + datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")}', 3)
        start_server = websockets.serve(self.ws_svr, '0.0.0.0', self.olog_cfg['svr_port'])
        asyncio.get_event_loop().run_until_complete(asyncio.gather(start_server, self.gather_report(), self.wechat_send()))
        asyncio.get_event_loop().run_forever()

    def gen_html(self, reports):
        self.read_olog_config()
        reports_html_templates_path = pathlib.Path(__file__).parent / 'reports.html'
        with reports_html_templates_path.open('r', encoding='utf-8') as fr:
            html = fr.read()
        items = ''
        lost_devices_count = 0
        err_devices_count = 0
        ok_devices_count = 0
        for device in self.olog_cfg.get('device_tasks', {}).keys():
            if reports.get(device, None) is None:
                reports[device] = 'LOST'
                lost_devices_count += 1
        for device, tasks in reports.items():
            lost_task_count = 0
            err_task_count = 0
            ok_task_count = 0
            if device not in self.olog_cfg.get('device_tasks', {}).keys():
                if not self.olog_cfg.get('device_tasks'):
                    self.olog_cfg['device_tasks'] = {}
                self.olog_cfg['device_tasks'][device] = []
                not_in_tasks_flag = ' [NEW]'
            else:
                not_in_tasks_flag = ''
            if tasks == 'LOST':
                is_device_lost = True
                tasks = {}
            else:
                is_device_lost = False
            for task in self.olog_cfg['device_tasks'][device]:
                if task not in tasks:
                    tasks[task] = {'state': 'lost', 'logdate': '', 'detail': ''}
            device_name = device.split('#')[0] if '#' in device else device
            device_addr = device.split('#')[1] if '#' in device else 'Addr not assign'
            device_info = f'<div class="mdui-panel-item-body"><p>{device_addr}</p><div class="mdui-panel" mdui-panel>'
            for task, info in tasks.items():
                if task not in self.olog_cfg['device_tasks'][device]:
                    self.olog_cfg['device_tasks'][device].append(task)
                    task += ' [NEW]'
                    if not not_in_tasks_flag:
                        not_in_tasks_flag = ' [NEW]'
                device_info += '<div class="mdui-panel-item">'
                if info['state'] == 'err':
                    err_task_count += 1
                    device_info += f'''
                        <div class="mdui-panel-item-header mdui-color-orange-900">{task}</div>
                        <div class="mdui-panel-item-body"><p>{info["detail"]}</p></div>'''
                elif info['state'] == 'ok':
                    ok_task_count += 1
                    device_info += f'''
                        <div class="mdui-panel-item-header mdui-color-green">{task}</div>
                        <div class="mdui-panel-item-body"><p>{info["detail"]}</p></div>'''
                elif info['state'] == 'lost':
                    lost_task_count += 1
                    device_info += f'''
                        <div class="mdui-panel-item-header mdui-color-red-900">{task}</div>
                        <div class="mdui-panel-item-body"><p>LOST: {device_addr}</p></div>'''
                device_info += '</div>'
            device_info += '</div></div>'
            if is_device_lost:
                item_color_class = 'mdui-color-red-900'
                device_title = f'''<div class="mdui-panel-item-title mdui-color-red-900">{device_name}{not_in_tasks_flag}</div>
                    <div class="mdui-panel-item-summary mdui-color-red-900">DEVICE LOST</div>'''
            elif err_task_count + lost_task_count > 0:
                item_color_class = 'mdui-color-orange-900'
                device_title = f'''<div class="mdui-panel-item-title">{device_name}{not_in_tasks_flag}</div>
                    <div class="mdui-panel-item-summary">
                        <a class="mdui-color-red-900">{lost_task_count} LOST</a>, 
                        <a class="mdui-color-orange-900">{err_task_count} ERR</a>, 
                        <a class="mdui-color-green">{ok_task_count} OK</a>
                    </div>'''
                err_devices_count += 1
            else:
                item_color_class = 'mdui-color-green'
                device_title = f'''<div class="mdui-panel-item-title mdui-color-green">{device_name}{not_in_tasks_flag}</div>
                    <div class="mdui-panel-item-summary">
                        <a class="mdui-color-green">OK</a>
                    </div>'''
                ok_devices_count += 1
            device_title = f'<div class="mdui-panel-item-header {item_color_class}">' + device_title + '<i class="mdui-panel-item-arrow mdui-icon material-icons">keyboard_arrow_down</i></div>'
            items += f'<div class="mdui-panel-item">{device_title}{device_info}</div>'
        index = f'''<h2>{self.device}</h2><p>{self.addr}</p><p>report time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | 
            <a class="mdui-text-color-red-900">{lost_devices_count} LOST</a>,
            <a class="mdui-text-color-orange-900">{err_devices_count} ERR</a>,
            <a class="mdui-text-color-green"> {ok_devices_count} OK</a></p>'''
        html = html.replace('{{ index }}', index).replace('{{ items }}', items)
        with self.olog_cfg_path.open('w', encoding='utf-8') as fw:
            json.dump(self.olog_cfg, fw, sort_keys=True, indent=4, separators=(',', ':'))
        return html
    
    def save_html(self, html):
        htmldir = self.olog_cfg['htmldir']
        htmlurl = self.olog_cfg['htmlurl']
        filename = hashlib.sha256((str(time.time()) + self.olog_cfg['token']).encode('utf-8')).hexdigest() + '.html'
        htmlpath = pathlib.Path(htmldir) / filename
        for p in pathlib.Path(htmldir).glob('**/*.html'):
            if time.time() - p.stat().st_mtime > 24 * 3600 * 7:
                os.remove(p)
        htmlpath.parent.mkdir(parents=True, exist_ok=True)
        with htmlpath.open('w', encoding='utf-8') as fw:
            fw.write(html)
        return htmlurl + filename


class Pipeline:

    def __init__(self):
        self.server = OlogSvr()
        self.client = OlogClient()


if __name__ == '__main__':
    fire.Fire(Pipeline)
