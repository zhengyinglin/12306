#coding=utf-8
# http://www.12306.cn/ 订票
# email 979762787@qq.com
# date 2014-01-13
# 参考  https://github.com/huzhifeng/51dingpiao/blob/master/new.py  用requests重写

import logging
logging.basicConfig(level=logging.DEBUG,
            format='%(asctime)s|%(filename)s|%(funcName)s|line:%(lineno)d|%(levelname)s|%(message)s',
            datefmt='%Y-%m-%d %X',
            filename='log.txt'
            )

import requests
import time
import os
import json
import random
import conf



# Global variables
stations = {}
queryTicketsTimes = 0

seatCode = {
  '特等' : 'P',
  '商务座': '9',
  '一等座': 'M',
  '二等座': 'O',
  '硬座': '1',
  '硬卧': '3',
  '软卧': '4'  
}

def printItem(items, name):
    msgs = items.get(name, "")
    if isinstance(msgs, list):
        for msg in msgs:
            print msg
    else:
        print msgs

#------------------------------------------------------------------------------
# 火车站点数据库初始化
# 每个站的格式如下:
# @bji|北京|BJP|beijing|bj|2   ---> @拼音缩写三位|站点名称|编码|拼音|拼音缩写|序号
def stationInit():
    global stations
    stations = {}
    if not os.path.isfile('station_name.js'):
        print 'start loading station_name.js'
        s = requests.Session()
        r = s.get('https://kyfw.12306.cn/otn/resources/js/framework/station_name.js',
                  timeout=5, verify=False)
        assert r.status_code == 200
        with open('station_name.js', 'wb') as fp:
             fp.write( r.content )
    else:
        print 'loading local station_name.js'
    with open('station_name.js') as fp:
        data = fp.read()
        data = data.partition('=')[2].strip("'") #var station_names ='..'
    for station in data.split('@')[1:]:
        items = station.split('|') # bjb|北京北|VAP|beijingbei|bjb|0
        stations[ items[1] ] = items[2]
    return stations


# Convert '2014-01-01' to 'Wed Jan 01 00:00:00 UTC+0800 2014'
def trainDate(d):
  t = time.strptime(d, '%Y-%m-%d')
  asc = time.asctime(t) # 'Wed Jan 01 00:00:00 2014'
  return (asc[0:-4] + 'UTC+0800 ' + asc[-4:]) # 'Wed Jan 01 00:00:00 UTC+0800 2014'


#简单装饰器
def fail_retry(times, ret_vals=(True,), exception=Exception):
    if not isinstance(ret_vals, (list, tuple) ):
        ret_vals = (ret_vals, )
    def inner(func):
        def _inner(*args, **kwargs):
            for i in xrange(times):
                if i:
                    logging.warning('run %s retry times %d', func.__name__, i)
                try:
                    ret = func(*args, **kwargs)
                    if ret in ret_vals:
                        return ret
                except exception, e:
                    logging.warning('exception: %s', e)
                    pass
            raise Exception('run %s times > %d' % (func.__name__, times) )
        return _inner
    return inner


class MyOrder(object):
  def __init__(self):
      self.username = conf.username 
      self.password = conf.password
      self.train_date = conf.train_date 
      self.from_city_name, self.to_city_name = conf.from_city_name, conf.to_city_name
      self.from_station_telecode = stations[ conf.from_city_name ] 
      self.to_station_telecode = stations[ conf.to_city_name ]
      self.passengers_id = conf.passengers_id
      self.station_train_code = conf.station_train_code
      self.printConfig()
      self.tour_flag = 'dc' # 单程dc/往返wf
      self.purpose_code = 'ADULT' # 成人票
      self.seatcode = seatCode[conf.seatname]
      self.passengers = [] # 乘客列表
      self.s = requests.Session() 
      self.order_train = None
      self.oldPassengerStr = ''
      self.passengerTicketStr = ''
      self.captcha = '1234' #订票时候验证码

  def printConfig(self):
      s = "\nusername = %s\ndate = %s\n%s--->%s\n\n" % ( self.username, self.train_date, 
            self.from_city_name, self.to_city_name )
      print unicode(s, 'utf-8')

  @fail_retry(3, exception=requests.Timeout)
  def _login_init(self):
      url = 'https://kyfw.12306.cn/otn/login/init'
      r = self.s.get(url, timeout=3, verify=False)
      return r.status_code == 200

  @fail_retry(3, exception=requests.Timeout)
  def _login_get_captcha(self):
      url = "https://kyfw.12306.cn/otn/passcodeNew/getPassCodeNew.do?module=login&rand=sjrand"
      r = self.s.get(url, timeout=3, verify=False)
      if r.status_code == 200:
          with open('randcode.png', 'wb') as fp:
               fp.write( r.content )
          return True
      else:
           print 'getPassCodeNew.do status_code %d != 200' %  r.status_code 

  @fail_retry(3, ret_vals=(True, False), exception=requests.Timeout)
  def _login_check_captcha(self, code):
      parameters = [
        ('randCode', code),
        ('rand', 'sjrand')
      ]
      url = 'https://kyfw.12306.cn/otn/passcodeNew/checkRandCodeAnsyn'
      r = self.s.post(url, parameters, timeout=3, verify=False)
      if r.status_code == 200:
         resp = r.json()
         logging.debug('checkRandCodeAnsyn resp  %s', resp)
         return  resp['status'] and resp[u'data'] == u'Y'
      else:
         print 'checkRandCodeAnsyn status_code %d != 200' %  r.status_code 

  @fail_retry(3, exception=requests.Timeout)
  def _login_start(self, captcha):
      parameters = [
        ('loginUserDTO.user_name', self.username),
        ('userDTO.password', self.password),
        ('randCode', captcha),
      ]
      url = 'https://kyfw.12306.cn/otn/login/loginAysnSuggest'
      r = self.s.post(url, parameters, timeout=5, verify=False)
      logging.debug("\n%s\n", r.request.headers) 
      if r.status_code != 200:
         print u"！！！.. 登陆失败 ..！！！"
         return 
      resp = r.json()
      logging.debug('loginAysnSuggest return %s', resp)
      if resp[u'data'].get('loginCheck', None)  == 'Y' :
         print u"----------------登陆成功^_^-------------------"
         return True
      else:
         print u"！！！.. 登陆失败 ..！！！"
         printItem(resp, 'messages')
       
  def _login(self):
      self._login_init()
      print u"接收登录验证码..."
      captcha = None
      while True:
         while not captcha:
             self._login_get_captcha()
             captcha = raw_input(u"输入新的验证码:".encode('gbk'))
         print u"校验登录验证码..."
         if self._login_check_captcha(captcha):
             logging.info("_login_check_captcha succ")
             break
         else: #失败重新输入
             captcha = raw_input(u"验证码错误重新输入:".encode('gbk'))
      print u"======>>>>正在登录..."
      return self._login_start(captcha)

  def get_passengers(self):
      print u'=====>>>>正在获取联系人...'
      self.passengers = [] # 乘客列表
      pfile = self.username + 'passengers'
      if not os.path.isfile(pfile):
          logging.info('start loading %s', pfile)
          parameters = [
             ('_json_att', ''),
          ]
          url = 'https://kyfw.12306.cn/otn/confirmPassenger/getPassengerDTOs'
          r = self.s.post(url, parameters, timeout=5, verify=False)
          assert r.status_code == 200
          resp = r.json()
          with open(pfile, 'w') as fp:
            fp.write(json.dumps(resp))
      else:
          logging.info('loading from local %s', pfile)
          with open(pfile) as fp:
              resp = json.loads( fp.read() )
      for passengers in resp['data']['normal_passengers']:
          if passengers['passenger_id_no'] in self.passengers_id:
              self.passengers.append(passengers)
              logging.info('add passengers %s', passengers['passenger_id_no'])
              print u'---------预定人：', passengers['passenger_name']
      if not self.passengers:
          print u'没有订票人信息'
          return False
      return True

  def login(self):
      return self._login() and self.get_passengers()

  @fail_retry(3, ret_vals=(True, False), exception=requests.Timeout)
  def queryTickets(self):
    parameters = [
      ('leftTicketDTO.train_date', self.train_date),
      ('leftTicketDTO.from_station', self.from_station_telecode), 
      ('leftTicketDTO.to_station', self.to_station_telecode), 
      ('purpose_codes', "ADULT"),
    ]
    #s = requests.Session()
    s = self.s
    r = s.get('https://kyfw.12306.cn/otn/leftTicket/query', params=parameters, 
              timeout=3, verify=False)

    global queryTicketsTimes
    queryTicketsTimes += 1
    print u'第 %d 次查询' % queryTicketsTimes

    if 200 != r.status_code:
       print u"请求出错 status_code = ", r.status_code
       return
    try:
        resp = r.json()
        #logging.debug("%r", resp)
        trains = resp['data']
        self.order_train = None
        return self._printTrains(trains)
    except Exception , e:
        print e
        return 
    return False
        

  def canpay(self, t):
    if t['canWebBuy'] != 'Y':
      return False
    its = ["zy_num", "ze_num", "rw_num", "yw_num", "rz_num", "yz_num", "wz_num"]
    for i in its:
      if t[i] == u'有' or t[i].isdigit() and int(t[i]) > 0 :
        return True
    return False

  def _printTrains(self, trains):
    #print u"第 %d 次余票查询结果如下:" % queryTicketsTimes
    #print u"序号/车次\t乘车站\t目的站\t一等座\t二等座\t软卧\t硬卧\t软座\t硬座\t无座"
    index = 1
    use_optional =  'all' in  self.station_train_code
    order_trains = {} #满足配置车辆
    optional = [] #是否选择其他的
    for train in trains:
        t = train['queryLeftNewDTO']
        if not self.canpay(t):continue
        if t['station_train_code'] in self.station_train_code:
           order_trains[ t['station_train_code'] ] = train
        elif use_optional:
           optional.append( train )
        '''print u"(%d)   %s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s"%(index,
            t['station_train_code'],
            t['from_station_name'],
            t['to_station_name'],
            t["zy_num"], # 一等
            t["ze_num"], # 二等  u'tz_num' 特等
            t["rw_num"],
            t["yw_num"],
            t["rz_num"],
            t["yz_num"],
            t["wz_num"])'''
        index += 1
        #'tz_num':特等座, zy_num: 一等座 "ze_num":二等 u'wz_num': 无座,
        '''     <ul id="seat-list">
        <li class="color333"><input type="checkbox" class="check" value="ZY" />一等座</li>
        <li class="color333"><input type="checkbox" class="check" value="ZE" />二等座</li>
        <li class="color333"><input type="checkbox" class="check" value="SWZ" />商务座</li>
        <li class="color333"><input type="checkbox" class="check" value="TZ" />特等座</li>
        <li class="color333"><input type="checkbox" class="check" value="YZ" />硬座</li>
        <li class="color333"><input type="checkbox" class="check" value="RZ" />软座</li>
        <li class="color333"><input type="checkbox" class="check" value="YW" />硬卧</li>
        <li class="color333"><input type="checkbox" class="check" value="RW" />软卧</li>
        <li class="color333"><input type="checkbox" class="check" value="GR" />高级软卧</li>
        <li class="color333"><input type="checkbox" class="check" value="WZ" />无座</li>
        </ul>'''
    
    if order_trains:
       for tcode in self.station_train_code:
          if tcode in order_trains:
            self.order_train = order_trains[tcode]
            break
    if not self.order_train and optional:
        self.order_train = random.choice(optional)
      
    if self.order_train :
        t = self.order_train['queryLeftNewDTO']
        print u'可以预定 ', t['station_train_code']
        return True
    else:
        print u'没有符合预定的车'
        return False
    

  def startOrder(self):
      print u'========>>>>>开始下订单...'
      if not self.initOrder():
         logging.warn('startOrder--initOrder failed')
         return  
      if not self.checkOrderInfo():
         logging.warn('startOrder--checkOrderInfo failed')
         return  
      #QQQQ 是否需要这个 !!!!!
      #if not self.getQueueCount():
      #   logging.warn('startOrder--getQueueCount failed')
      #   return  
      for i in range(3):
         if self.confirmSingleForQueue():
            break
         logging.warn('startOrder--confirmSingleForQueue failed')
      else:
         return 
      if not self.queryOrderWaitTime():
         logging.warn('startOrder--getQueueCount failed')
         return  


  def initOrder(self):
      assert self.order_train 
      t = self.order_train['queryLeftNewDTO']
      print u"======>>>>准备下单..."
      print u'%(station_train_code)s  %(start_station_name)s --> %(end_station_name)s  %(start_time)s -- %(arrive_time)s' % t
      parameters = [
          ('secretStr', self.order_train['secretStr'] ),
          ('train_date', self.train_date),
          ('back_train_date', self.train_date),
          ('tour_flag', self.tour_flag),
          ('purpose_codes', self.purpose_code),
          ('query_from_station_name', self.from_city_name),
          ('query_to_station_name', self.to_city_name),
          ('undefined', '')
      ]
      url = 'https://kyfw.12306.cn/otn/leftTicket/submitOrderRequest'
      r = self.s.post(url, parameters, timeout=3, verify=False)
      logging.debug('%s', r.request.headers)
      if r.status_code != 200:
        print '!!! 准备下单 失败 submitOrderRequest status_code %d != 200' %  r.status_code 
        return 
      resp = r.json()
      logging.debug('submitOrderRequest resp  %s', resp)
      if not resp['status'] :
        print 'submitOrderRequest failed'
        printItem(resp, 'messages')
        return 
      logging.info('submitOrderRequest succ')
      print u"====>>>>订单初始化..."
      parameters = [
          ('_json_att', ''),
      ]
      url = 'https://kyfw.12306.cn/otn/confirmPassenger/initDc'
      r = self.s.post(url, parameters, timeout=5, verify=False)
      #一个xml文件
      logging.debug('%s', r.request.headers)
      #logging.debug("%r", r.text )
      data = r.text
      i = data.find("globalRepeatSubmitToken")
      j = data.find(";", i)
      if i == -1 or j == -1:
          print u'找不到 globalRepeatSubmitToken'
          return 
      buff = data[i:j]
      #"globalRepeatSubmitToken = \\'690c9a8975954438c309eb416e0bb871\\'"
      self.repeatSubmitToken = buff.partition('=')[-1].strip(" \\'")
      logging.info("globalRepeatSubmitToken=%s", self.repeatSubmitToken)
      i = data.find("key_check_isChange")
      j = data.find(",", i)
      if i == -1 or j == -1:
          print u'找不到 key_check_isChange'
          return 
      buff = data[i:j]
      #'key_check_isChange\':\'4F4DF30AE91A5F69852DD8B2E47AFFC2273D9907979D8F854445FC4E\',
      self.keyCheckIsChange = buff.partition(':')[-1].strip(" \\'")
      logging.info("key_check_isChange=%s", self.keyCheckIsChange)
      print u"=======订单初始化成功..."
      return True
   
  @fail_retry(3, exception=requests.Timeout)
  def _order_get_captcha(self):
      url = "https://kyfw.12306.cn/otn/passcodeNew/getPassCodeNew?module=passenger&rand=randp"
      r = self.s.get(url, timeout=3, verify=False)
      if r.status_code == 200:
          with open('randcode.png', 'wb') as fp:
              fp.write( r.content )
          return True
      else:
          print 'getPassCodeNew status_code %d != 200' %  r.status_code 

  @fail_retry(3, ret_vals=(True, False), exception=requests.Timeout)
  def _order_check_captcha(self, code):
      parameters = [
        ('randCode', code),
        ('rand', "randp"),
        ('_json_att', ''),
        ('REPEAT_SUBMIT_TOKEN', self.repeatSubmitToken)
      ]
      url = 'https://kyfw.12306.cn/otn/passcodeNew/checkRandCodeAnsyn'
      r = self.s.post(url, parameters, timeout=3, verify=False)
      logging.debug('%s', r.request.headers)
      if r.status_code == 200:
         resp = r.json()
         logging.debug('checkRandCodeAnsyn resp  %s', resp)
         return  resp['status'] and resp[u'data'] == u'Y'
      else:
         print 'checkRandCodeAnsyn status_code %d != 200' %  r.status_code 


  def checkOrderInfo(self):
      captcha = None
      while True:
        print u"======>>>>接收订单验证码..."
        while not captcha:
            self._order_get_captcha()
            print '--' * 10 , '\n\n'
            captcha = raw_input(u"输入验证码:".encode('gbk'))
            captcha = captcha.strip()
        print u"======>>>>正在校验订单验证码..."
        if self._order_check_captcha(captcha):
            logging.info("_order_check_captcha succ")
            break
        else:
            captcha = raw_input(u"验证码错误重新输入:".encode('gbk'))
      print u"-------校验订单验证码成功--------"
      self.captcha = captcha
      '''
      passengerTicketStr
      第一个项  
      第二个项  0 好像随机
      第3个项   1 成人
      第4个项   名字
      第5个项   类型1 身份证类型
      第6个项   身份证或者其他
      第7个项   电话号码
      第8个项   N
      有多个用 _ 连接

      oldPassengerStr
      第1个项   名字
      第2个项   类型1 身份证类型
      第3个项   身份证或者其他
      第4个项   1
      有多个用 _ 连接 （捉包这里最后还要加_）

      单人
      cancel_flag=2&bed_level_order_num=000000000000000000000000000000
      &passengerTicketStr=M,0,1,邱xx,1,3xxx2xxx89xxxx22,,N
      &oldPassengerStr=邱xx,1,3xxx2xxx89xxxx22,1_
      &tour_flag=dc&randCode=fmkb&_json_att=&REPEAT_SUBMIT_TOKEN=2858bb493bf8178e5e50d1e84732085c
      多人
      cancel_flag=2&bed_level_order_num=000000000000000000000000000000
      &passengerTicketStr=O,0,1,郑xx,1,4xxx2198xxx9xxx4,1xx55xxx93,N_O,0,1,邱xx,1,3xxx2xxx89xxxx22,,N_M,0,1,曾xx,1,4xxxx1xx34xxx5,,N
      &oldPassengerStr=郑xx,1,4xxx2198xxx9xxx4,1_邱xx,1,3xxx2xxx89xxxx22,1_曾xx,1,4xxxx1xx34xxx5,1_
      &tour_flag=dc&randCode=q7aq&_json_att=&REPEAT_SUBMIT_TOKEN=7d60e747e5c230a312e18eaac05eb35f
      '''
      ops = []
      pts = []
      for p in self.passengers:
        ops.append( u'%s,%s,%s,1' % (p['passenger_name'], p['passenger_id_type_code'], p['passenger_id_no'])  )
        pts.append( u'%s,0,1,%s,%s,%s,%s,N' % (self.seatcode, p['passenger_name'],p['passenger_id_type_code'],
            p['passenger_id_no'],p['mobile_no']) )

      self.oldPassengerStr = '_'.join( [ s.encode('utf-8') for s in ops ] ) + '_'
      self.passengerTicketStr = '_'.join( [ s.encode('utf-8') for s in pts ] )

      parameters = [
         ('cancel_flag', '2'), 
         ('bed_level_order_num', '000000000000000000000000000000'), 
         ('passengerTicketStr', self.passengerTicketStr),
         ('oldPassengerStr', self.oldPassengerStr),
         ('tour_flag', self.tour_flag),
         ('randCode', self.captcha),
         ('_json_att', ''),
         ('REPEAT_SUBMIT_TOKEN', self.repeatSubmitToken),
      ]

      print u"=======>>>>>>正在递交用户信息..."
      url = 'https://kyfw.12306.cn/otn/confirmPassenger/checkOrderInfo'
      r = self.s.post(url, parameters, timeout=3, verify=False)
      logging.debug('%s\n%s', r.request.headers, r.request.body)
      logging.debug("%r", r.text)
      if r.status_code != 200:
         print 'checkOrderInfo status_code %d != 200' %  r.status_code 
         return 
      resp = r.json()
      logging.debug('checkOrderInfo resp  %s', resp)
      if resp['status'] and  resp[u'data'].get('submitStatus', False) :
         print u"---------递交用户信息成功--------" 
         return True
      else:
         print u"递交用户信息失败"
         printItem(resp['data'], 'errMsg') 
         printItem(resp, 'messages')


  def getQueueCount(self):
    print u"========>>>>>查询排队情况..."
    t = self.order_train['queryLeftNewDTO']
    parameters = [
      ('train_date', trainDate(self.train_date) ),
      ('train_no', t['train_no'] ),
      ('stationTrainCode', t['station_train_code'] ),
      ('seatType', '1' ), 
      ('fromStationTelecode', t['from_station_telecode'] ),
      ('toStationTelecode', t['to_station_telecode'] ),
      ('leftTicket', t['yp_info'] ),
      ('purpose_codes', '00' ), 
      ('_json_att', ''),
      ('REPEAT_SUBMIT_TOKEN', self.repeatSubmitToken)
    ]
    url = 'https://kyfw.12306.cn/otn/confirmPassenger/getQueueCount'
    r = self.s.post(url, parameters, timeout=3, verify=False)
    logging.debug('%s', r.request.headers)
    if r.status_code != 200:
        print u'getQueueCount status_code %d != 200' %  r.status_code 
        return 
    resp = r.json()
    logging.debug('getQueueCount resp  %s', resp)
    if not resp['status'] :
        print u"!!!!! 查询排队情况失败 !!!!!"
        printItem(resp, 'messages')
        return 
    op1 = resp['data'].get('op_1', '') == "true"
    op2 = resp['data'].get('op_2', '') == "true"
    ticket =  resp['data'].get('ticket', '')
    print op1, op2 , ticket
    #检查队列，是否推出？？
    return True


  def confirmSingleForQueue(self):
    print u"=======>>>>>提交订单排队..."
    t = self.order_train['queryLeftNewDTO']
    parameters = [
      ('passengerTicketStr', self.passengerTicketStr),
      ('oldPassengerStr', self.oldPassengerStr),
      ('randCode', self.captcha),
      ('purpose_codes', '00'),
      ('key_check_isChange', self.keyCheckIsChange),
      ('leftTicketStr', t['yp_info'] ),
      ('train_location', t['location_code'] ),
      ('_json_att', ''),
      ('REPEAT_SUBMIT_TOKEN', self.repeatSubmitToken),
    ]
    url = 'https://kyfw.12306.cn/otn/confirmPassenger/confirmSingleForQueue'
    r = self.s.post(url, parameters, timeout=3, verify=False)
    if r.status_code != 200:
        print 'confirmSingleForQueue status_code %d != 200' %  r.status_code 
        return
    resp = r.json()
    logging.debug('confirmSingleForQueue resp  %s', resp)
    if resp['status'] and resp['data'].get('submitStatus', False) :
        print u"=====>>>>订单排队中, 先别激动，接下来看你的运气和人品了"
        return True
    else:
        print u"!!!!! 提交订单排队失败 !!!!!"
        printItem(resp, 'messages')


  def queryOrderWaitTime(self):
    print u"========>>>>等待订单流水号..."
    url = 'https://kyfw.12306.cn/otn/confirmPassenger/queryOrderWaitTime?random=%d&tourFlag=dc&_json_att=&REPEAT_SUBMIT_TOKEN=%s'%(int(time.time()), self.repeatSubmitToken)
    r = self.s.get(url, timeout=3, verify=False)
    if r.status_code != 200:
        print 'queryOrderWaitTime status_code %d != 200' %  r.status_code 
        return
    resp = r.json()
    logging.debug('queryOrderWaitTime resp  %s', resp)
    if resp['status'] and resp['data'].get('orderId', None):
        print u"----------订单流水号为:", resp['data']['orderId']
        # 正式提交订单
        return self.payOrder(resp['data']['orderId'] )
    else:
      print u"!!!!  等待订单流水号失败 !!!!!!!"
      printItem(resp['data'], 'messages')
      print u"等待waitTime=%s,waitCount=%s" % (resp['data'].get('waitTime', 'None') , resp['data'].get('waitCount', 'None') )
      time.sleep(0.5)
      return self.queryOrderWaitTime()


  def payOrder(self, orderId):
    print u"=======>>>>>等待订票结果..."
    parameters = [
      ('orderSequence_no', orderId),
      ('_json_att', ''),
      ('REPEAT_SUBMIT_TOKEN', self.repeatSubmitToken),
    ]
    url = 'https://kyfw.12306.cn/otn/confirmPassenger/resultOrderForDcQueue'
    r = self.s.post(url, parameters, timeout=3, verify=False)
    if r.status_code != 200:
        print 'resultOrderForDcQueue status_code %d != 200' %  r.status_code 
        return
    resp = r.json()
    logging.debug('resultOrderForDcQueue resp  %s', resp)
    if not resp['status'] or not resp['data'].get('submitStatus', False):
        print u"!!!! 等待订票结果失败 !!!!!!"
        printItem(resp, 'messages')
        printItem(resp['data'], 'errMsg')
        return 
    print u"======>>>>等待订票结果...."
    url = 'https://kyfw.12306.cn/otn/payOrder/init?random=%d' %  int(time.time())
    parameters = {
      '_json_att': '',
      'REPEAT_SUBMIT_TOKEN': self.repeatSubmitToken,
    }
    r = self.s.post(url, parameters, timeout=5, verify=False)
    data = r.text
    if data.find(u'席位已锁定') != -1:
        print u"人品爆发  订票成功^_^请在45分钟内完成网上支付,否则系统将自动取消"
        return True
    else:
        print u"!!!!!  订票失败 !!!!!!"
        logging.warn('%s', data)


def main():
  logging.info('start runing')
  stationInit()
  order = MyOrder()
  if not order.login():
     return 
  logging.info('login done')
  while True:
     try:
       if not order.queryTickets():
          print u'%d 秒后重试' % conf.QueryTicketSeconds
          time.sleep(conf.QueryTicketSeconds)
          continue
       t = order.order_train['queryLeftNewDTO']
       print u'预定 ', t['station_train_code']
       #raw_input(u'回车开始下单'.encode('gbk'))
       order.startOrder()
     except Exception, e:
        print e


if __name__=="__main__":
   main()
   raw_input('press any key to exit...')
