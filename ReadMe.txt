#coding=utf-8
12306火车票查询购买（成人票）
主要参考  https://github.com/huzhifeng/51dingpiao/blob/master/new.py 

依赖库requests

主文件 12306.py
配置文件 conf.py ——配置用户名密码火车等信息

------------第一次运行12306.py 后会会生产一下文件
log.txt  程序日志 可以删除
station_name.js   12306火车站点信息，如果想获得最新的信息可以删除，程序会重新下载
用户名+passengers  12306 添加的联系人信息
randcode.png  验证码图片 程序不会自动获得验证码，需要手动输入
