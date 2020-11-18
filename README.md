# Olog: one log, online log

## 简介

这是一个用于监视不同设备的任务运行状况，并在异常时及时报警推送到微信端的项目。

如果没有异常状况，也会每日生成相关报告并推送到微信端。

## 原理

这个脚本包含了日志汇聚服务器端和客户端。

汇聚服务器端会运行一个websocket端口，用来将不同设备的日志汇聚在一起。

客户端会监视`olog.cfg`配置文件中`log_dirs`指定的文件夹，例如/var/ologs，当这个文件夹内出现日志文件时，会采取不同的应对措施：

#### 错误和警告日志
监视文件夹内，出现.err .msg为后缀的日志时，就会立刻自动推送消息和日志摘要到微信端。

#### 每日报告
每天的定时(`olog.cfg`配置文件中的`report_time`指定汇报时间)会进行一次日志扫描和信息汇总，将设备情况和日志情况汇总到olog汇聚服务器，随后汇聚服务器端发送每日报告到微信端。

设备汇聚报告的内容包括：
- LOST: 设备已离线
- ERR: 设备中有任务有异常
- OK: 设备一切正常

任务汇聚报告的内容包括：
- LOST: 在配置文件tasks中存在的，但是未在日志汇聚中找到相关日志内容的任务
- ERR: 运行错误的任务
- OK: 运行正常的任务

报告中有\[NEW\]字样的为历史记录中不存在的新任务或新设备，会自动将其记录。如需修改设备和任务列表，可以在`olog.cfg`中修改`device_tasks`的内容。

## 使用方法

#### 下载程序
```shell
git clone https://github.com/RainGather/olog.git
```

#### 安装环境
```shell
pip install -i https://pypi.douban.com/simple -r requirements.txt
```

#### 生成配置文件
```shell
python3 olog.py
```
第一次运行会询问是否生成配置文件，输入y并回车，会生成一个配置文件模板

#### 修改配置文件
配置文件是json格式，分别为：
- device: 当前设备名称，格式是`设备名#ssh连接地址`。
- svr_ip: olog汇总服务器的ip，可以是网址，如果是服务器端则可以不填写
- svr_port: olog汇总服务器的端口，服务器端填写该端口号则会将该端口号作为监听端口号
- report_time: 报告时间，仅olog汇总服务器需要填写
- log_keep_days: 自动清除超过该天数的日志
- token: [wxpusher](https://wxpusher.zjiecode.com/docs/#/)获取到的token
- uids: [wxpusher](https://wxpusher.zjiecode.com/docs/#/)获取到的uid
- tasks: 仅服务器需要填写，一个字典，记录了不同设备应该运行的任务。系统会根据日志文件名来判断任务名，日志文件名中以**@task name@**的格式设置任务名。
- htmldir: 生成的报告html存放的本地路径，需自行做好配置可供公网访问
- htmlurl: 报告存放服务器的url

#### 运行
```shell
# 服务器端运行
python3 olog.py server run
# 客户端运行
python3 olog.py client run
```

## 案例

假设你有如下需求：

- alisrv: 阿里云服务器一台，有个绑定的域名为：www.xxx.com，服务器内用nginx运行着自己的个人网站，其中/www是nginx的root根目录，可以提供html访问
- comsrv: 公司内服务器一台，里面有个mysql服务必须时刻保持运行状态，一旦异常需要立刻报警
- backupsrv: 备份服务器一台，里面有个基于rsync的数据备份，需要每天都有一次备份
- respi: 一台树莓派，跑着一个基于mqtt的物联网项目smarthome

可以做如下配置：


#### 注册wxpusher

去[wxpusher](https://wxpusher.zjiecode.com/docs/#/)注册，获取token和uid


#### 准备汇总服务器

将alisrv作为汇总服务器，配置alisrv的olog.cfg如下：

```python
{
    "device":"alisrv#root@122.112.54.123:22",
    "log_dirs": [
        "/ologs"
    ]
    "log_keep_days":360,
    "report_time":"11:00",
    "svr_port":8765,
    "token":"AT_XXXXXXXXXXXXXXXXXXXXXXX",
    "uids":["UID_XXXXXXXXXXXXXXXXXXXXX"],
    "htmldir": "/www/olog_html",
    "htmlurl": "http://www.xxx.com/olog_html/"
}
```

之后运行服务端和客户端

```shell
# 注意python加 -u 参数，否则输出重定向会有缓冲，不会立刻保存在重定向文件中。
nohup python3 -u olog.py client run 1>/ologs/olog_client.log 2>/ologs/olog_client.err &
nohup python3 -u olog.py server run 1>/ologs/olog_server.log 2>/ologs/olog_server.err &
```

可以将这些运行命令写入crontab中，用@reboot触发，这样每次设备开机后都会在后台自动运行。

随后在alisrv中写好脚本监视nginx进程，例如：

```shell
[ -z "$(ps -ef | grep nginx | grep -v grep)" ] && echo "nginx not running!" > /ologs/nginx.err
```

并将该脚本加入crontab定时运行即可监视。当nginx停止运行时，会在/ologs目录下生成nginx.err文件，此时olog就会监视到并推送警报到你的手机。

3. 将comsrv、backupsrv和respi都作为client，配置他们的olog.cfg如下(以comsrv为例)：

```python
{
    "device":"comsrv#ubuntu@10.20.0.233:22",
    "log_dirs": [
        "/ologs"
    ]
    "log_keep_days":360,
    "svr_ip":"www.xxx.com",
    "svr_port":8765,
    "token":"AT_XXXXXXXXXXXXXXXXXXXXXXX",
    "uids":["UID_XXXXXXXXXXXXXXXXXXXXX"]
}
```

同样可以将所需监视的内容写成脚本后用crontab去运行即可。
