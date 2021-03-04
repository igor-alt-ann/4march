#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re
import threading
import time

import pystrix

import requests
import logging
import logging.handlers
import random
import sys

#TURL='https://directapi.city-mobil.ru/taxiserv/api/internal/1.0.0/'
TURL='http://directapi-internal.city-mobil.ru/taxiserv/api/internal/1.0.0/'
TURL_TEST='https://t.city-mobil.ru/taxiserv/api/internal/1.0.0/'

# Включаем логирование
class LogFilter(logging.Filter):
    def __init__(self, method):
        self.method=method
        logging.Filter.__init__(self)

    def filter(self, record):
        record.name="%s:%d"%(record.name, FastAGIServer.thread_local.calls)
        return True

LOG_FILE='/var/log/asterisk/fastagi.log'
#logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

log_handler=logging.handlers.WatchedFileHandler(LOG_FILE)
formatter=logging.Formatter('%(asctime)s [%(process)d:%(thread)d] %(levelname)s %(name)s %(message)s')
log_handler.setFormatter(formatter)
logger=logging.getLogger()
logger.addHandler(log_handler)
logger.setLevel(logging.DEBUG)

##JSON logs
## import json_log_formatter
## class CustomisedJSONFormatter(json_log_formatter.JSONFormatter):
##     def json_record(self, message, extra, record):
##         extra=super().json_record(message, extra, record)
##         #extra['message'] = message
##         extra['name'] = record.name
##         return extra
## 
## LOG_JSON='/var/log/asterisk/fastagi_json.log'
## formatter = CustomisedJSONFormatter()
## 
## json_handler = logging.handlers.WatchedFileHandler(LOG_JSON)
## json_handler.setFormatter(formatter)
## logger.addHandler(json_handler)
## logger.setLevel(logging.DEBUG)

logging.info('<<< FastAGI starting >>>')

##decorator
def wrapper(class_method):
        def _impl(self, *method_args, **method_kwargs):
            #self, agi, args, kwargs, match, path
            #       0    1       2      3      4
            match=method_args[3]
            method=match.group(0)
            logger=logging.getLogger(method)
            start=time.time()
            ##duration of request
            FastAGIServer.thread_local.reqdur=0
            if method in FastAGIServer.call_count:
                FastAGIServer.call_count[method]+=1
            else:
                FastAGIServer.call_count[method]=1
            FastAGIServer.thread_local.calls=FastAGIServer.call_count[method]
            logger.info("args:[%s] kwargs:[%s] thrs: %d",method_args[1],method_args[2],threading.active_count())
            method_kwargs['logger']=logger
            ret=class_method(self, *method_args, **method_kwargs)
            logger.info('agi dur: %d', (time.time()-start-FastAGIServer.thread_local.reqdur)*1000)
            logger.info('finish dur: %d',(time.time()-start)*1000)
            return ret
        return _impl

class FastAGIServer(threading.Thread):
    """
    A simple thread that runs a FastAGI server forever.
    """
    _fagi_server = None #The FastAGI server controlled by this thread
    #counters dict
    call_count={}
    #thread local data
    thread_local=threading.local()

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True

        #For prod
        self._fagi_server = pystrix.agi.FastAGIServer()
        #For debug
        #self._fagi_server = pystrix.agi.FastAGIServer(interface='127.0.0.1', port=45467,)

        #self._fagi_server.register_script_handler(re.compile(r'^getvoipcallroute$'), self.getvoipcallroute)
        #self._fagi_server.register_script_handler(re.compile(r'^getmaskbyphone$'), self.getmaskbyphone)
        #self._fagi_server.register_script_handler(re.compile(r'^getclientphonebydrivercall$'), self.get_driver_or_client_by_call)
        #self._fagi_server.register_script_handler(re.compile(r'^getdriverphonebyclientcall$'), self.get_driver_or_client_by_call)

        self.add_handler('getvoipcallroute', self.getvoipcallroute)
        self.add_handler('getmaskbyphone', self.getmaskbyphone)
        self.add_handler('getclientphonebydrivercall', self.get_driver_or_client_by_call)
        self.add_handler('getdriverphonebyclientcall', self.get_driver_or_client_by_call)
        self.add_handler('call_api_method', self.call_api_method)
        self.add_handler('call_api_method_test', self.call_api_method_test)
        self.add_handler('getphonebymask', self.getphonebymask)
        self.add_handler('sipp_test', self.sipp_test)
        self.add_handler('mixer', self.mixer)

        self._fagi_server.register_script_handler(None, self._noop_handler)

    def add_handler(self, name, handler):
        self._fagi_server.register_script_handler(re.compile(r'^'+name+r'$'), handler)
        logging.getLogger(name).addFilter(LogFilter(name))

    def get_logger(self, method, args, kwargs):
        logger=logging.getLogger(method)
        if method in FastAGIServer.call_count:
            FastAGIServer.call_count[method]+=1
        else:
            FastAGIServer.call_count[method]=0
        FastAGIServer.thread_local.calls=FastAGIServer.call_count[method]
        logger.info("args:[%s] kwargs:[%s] thrs: %d",args,kwargs,threading.active_count())
        return logger

    def set_cdr(self, agi, route, logger):
        ##CDR variables
        if 'order_id' in route and route['order_id'] != '0':
            agi.execute(pystrix.agi.core.SetVariable('MASTER_CHANNEL(HASH(__CDR,id_order))',route['order_id']))
        if 'id_driver' in route:
            agi.execute(pystrix.agi.core.SetVariable('MASTER_CHANNEL(HASH(__CDR,id_driver))',route['id_driver']))
        if 'id_client' in route:
            agi.execute(pystrix.agi.core.SetVariable('MASTER_CHANNEL(HASH(__CDR,id_client))',route['id_client']))
        if 'id_company' in route:
            agi.execute(pystrix.agi.core.SetVariable('MASTER_CHANNEL(HASH(__CDR,companyid))',route['id_company']))
        if 'id_locality' in route:
            agi.execute(pystrix.agi.core.SetVariable('MASTER_CHANNEL(HASH(__CDR,id_locality))',route['id_locality']))

        ##new CDR element Wed Mar 13 15:23:03 MSK 2019
        if 'cdr' in route:
            cdr=route['cdr']
            for k in cdr:
                agi.execute(pystrix.agi.core.SetVariable('MASTER_CHANNEL(HASH(__CDR,'+k+'))',cdr[k]))
                logger.debug('Set CDR %s=%s',k, cdr[k])


    #######################
    @wrapper
    def getvoipcallroute(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            uniqueid = agi.execute(pystrix.agi.core.GetVariable('UNIQUEID'))
            phone = agi.execute(pystrix.agi.core.GetVariable('CALLERID(num)'))
            entry = agi.execute(pystrix.agi.core.GetVariable('agi_entry'))
            logger.debug('call uniqid: %s phone number: %s agi_entry: %s', uniqueid, phone, entry)
            if not phone is None:
                # Запрос информации есть или нет завершенные заказы
                # phone - номер телефона звонившего
                # agi_entry - номер на который позвонил абонент
                # period - время прошедшее с момента завершения заказа
                # Парамеры phone, agi_entry и period обязательны, если их нет, то ничего не делаем
                if not phone or not entry or not uniqueid:
                    logger.debug('call getvoipcallroute without phone or entry or uniqueid')
                    return

                try:
                    # Создаем словарь с аргументами
                    args = {'phone': phone, 'entry': entry, 'call_uniqueid': uniqueid}
                    # Делаем запрос к API, передаем аргументы для запроса и задаем timeout
                    start=time.time()
                    r = requests.get(TURL+'getvoipcallroute', params=args, timeout=2)
                    reqdur=time.time()-start
                    FastAGIServer.thread_local.reqdur=reqdur
                    logger.info('request dur: %d',reqdur*1000)

                    # Обрабатываем ответ, если телефон найден, возвращаем 1
                    data = r.json()
                    if data["data"]:
                        route = data["data"]
                        logger.debug('phone: %s have this result: %s', phone, route)
                    else:
                        logger.debug('phone: %s dont have result', phone)
                        return
                except:
                    logger.exception('phone: %s have exception while query taxiserv api', phone)
                    agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'API_ERROR'))
                    return

                agi.execute(pystrix.agi.core.SetVariable('__IS_DRIVER', route["is_driver"]))
                agi.execute(pystrix.agi.core.SetVariable('__IS_CLIENT', route["is_client"]))
                agi.execute(pystrix.agi.core.SetVariable('__HAS_ORDER', route["has_order"]))
                agi.execute(pystrix.agi.core.SetVariable('__ORDERID', route["order_id"]))
                if "qpriority" in route:
                    agi.execute(pystrix.agi.core.SetVariable('__QUEUE_PRIO',route["qpriority"]))

                #проверяем есть ли элемент ivr
                #if route["is_client"] == 1 and route["has_order"] == 1 and 'ivr' in route:
                if 'ivr' in route:
                   if 'files' in route['ivr']:
                      agi.execute(pystrix.agi.core.SetVariable('__ANNOUNCEMENT','&'.join(route['ivr']['files'])))

                   if "onhangup_method" in route['ivr']:
                      agi.execute(pystrix.agi.core.SetVariable('__onhangup_method',route['ivr']['onhangup_method']))

                if 'wait_DTMF' in route:
                    agi.execute(pystrix.agi.core.SetVariable('__wait_DTMF',route['wait_DTMF']))

                ##Set CDR vars
                self.set_cdr(agi,route,logger)

        except:
            logger.exception('exception')
            agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################


    #######################
    @wrapper
    def getmaskbyphone(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            uniqueid = agi.execute(pystrix.agi.core.GetVariable('UNIQUEID'))
            phone = agi.execute(pystrix.agi.core.GetVariable('CALLERID(num)'))
            entry = agi.execute(pystrix.agi.core.GetVariable('agi_entry'))
            logger.debug('call uniqid: %s phone number: %s agi_entry: %s', uniqueid, phone, entry)
            if phone != None:
                # Запрос информации есть или нет завершенные заказы
                # phone - номер телефона звонившего
                # agi_entry - номер на который позвонил абонент
                # period - время прошедшее с момента завершения заказа
                if not phone or not entry:
                    logger.debug('call getmaskbyphone without phone or entry')
                    return

                try:
                    # Создаем словарь с аргументами
                    args = {'phone': phone, 'entry': entry}
                    # Делаем запрос к API, передаем аргументы для запроса и задаем timeout
                    start=time.time()
                    r = requests.get(TURL+'getmaskbyphone', params=args, timeout=2)
                    reqdur=time.time()-start
                    FastAGIServer.thread_local.reqdur=reqdur
                    logger.info('request dur: %d',reqdur*1000)

                    # Обрабатываем ответ, если телефон найден, возвращаем 1
                    data = r.json()
                    if data["data"]:
                        route = data["data"]
                        logger.debug('phone: %s have this result: %s', phone, route)
                    else:
                        logger.debug('phone: %s dont have result', phone)
                        return
                except:
                    logger.exception('phone: %s have exception while query taxiserv api', phone)
                    agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'API_ERROR'))
                    return

                logger.debug('route mask: %s', route["mask"])
                agi.execute(pystrix.agi.core.SetVariable('__MASKED_PHONE_NUMBER', route["mask"]))
        except:
            logger.exception('exception')
            agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################


    #######################
    @wrapper
    def get_driver_or_client_by_call(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            uniqueid = agi.execute(pystrix.agi.core.GetVariable('UNIQUEID'))
            phone = agi.execute(pystrix.agi.core.GetVariable('CALLERID(num)'))
            entry = agi.execute(pystrix.agi.core.GetVariable('agi_entry'))
            id_order = agi.execute(pystrix.agi.core.GetVariable('ORDERID'))
            logger.debug('call uniqid: %s phone number: %s agi_entry: %s id_order: %s', uniqueid, phone, entry, id_order)
            if phone != None:
                # Запрос информации есть или нет завершенные заказы
                # phone - номер телефона звонившего
                # agi_entry - номер на который позвонил абонент
                # period - время прошедшее с момента завершения заказа

                # Парамеры phone, agi_entry и period обязательны, если их нет, то ничего не делаем
                if not phone or not entry:
                    logger.debug('call %s without phone or entry', method)
                    return

                try:
                    # Создаем словарь с аргументами
                    args = {'phone': phone, 'entry': entry, 'id_order': id_order}
                    # Делаем запрос к API, передаем аргументы для запроса и задаем timeout
                    start=time.time()
                    r = requests.get(TURL+method, params=args, timeout=2)
                    reqdur=time.time()-start
                    FastAGIServer.thread_local.reqdur=reqdur
                    logger.info('request dur: %d',reqdur*1000)

                    # Обрабатываем ответ, если телефон найден, возвращаем 1
                    data = r.json()
                    if data["data"]:
                        route = data["data"]
                        logger.debug('phone: %s have this result: %s', phone, route)
                    else:
                        logger.debug('phone: %s dont have result', phone)
                        return
                except:
                    logger.exception('phone: %s have exception while query taxiserv api', phone)
                    agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'API_ERROR'))
                    return

                if 'phone' in route:
                    agi.execute(pystrix.agi.core.SetVariable('__PHONE_HIDE_NUMBER', route["phone"]))

                ##Set CDR vars
                self.set_cdr(agi,route,logger)

        except:
            logger.exception('exception')
            agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################

    #######################
    @wrapper
    def call_api_method(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            uniqueid = agi.execute(pystrix.agi.core.GetVariable('UNIQUEID'))
            muniqueid = agi.execute(pystrix.agi.core.GetVariable('MASTER_CHANNEL(UNIQUEID)'))
            logger.info('Start call_api_method for UNIQUEID=%s/%s'%(muniqueid,uniqueid))

            method_name = agi.execute(pystrix.agi.core.GetVariable('METHOD_NAME'))
            if method_name is None:
                logger.error('Error METHOD_NAME not set')
                return
            method_type = agi.execute(pystrix.agi.core.GetVariable('METHOD_TYPE'))
            if method_type is None:
                method_type = 'post'
            if method_type.lower() == 'get':
                method_type = 'get'
            else:
                method_type = 'post'

            logger.info('METHOD_NAME: %s METHOD_TYPE: %s'%(method_name, method_type))
            params={}
            params_str = agi.execute(pystrix.agi.core.GetVariable('METHOD_PARAMS'))
            if params_str is not None:
                for p in params_str.rsplit('-'):
                  params[p]=agi.execute(pystrix.agi.core.GetVariable(p))

            logger.info('params: %s',params)
            try:
                # Делаем запрос к API, передаем аргументы для запроса и задаем timeout
                start=time.time()
                if method_type == 'get':
                    ret = requests.get(TURL+method_name, params=params, timeout=2)
                else:
                    ret = requests.post(TURL+method_name, data=params, timeout=2)
                reqdur=time.time()-start
                FastAGIServer.thread_local.reqdur=reqdur
                logger.info('request dur: %d',reqdur*1000)
                logger.debug(ret)
            except:
                logger.exception('Exception while query taxiserv api')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'API_ERROR'))
                return

            data = ret.json()
            if data["data"]:
                result = data["data"]
                logger.debug('data: %s', result)
                ##interpret cdr specialy
                for k in result:
                  if k == 'cdr':
                     self.set_cdr(agi,result,logger)  
                  elif type(result[k]) is list:
                     agi.execute(pystrix.agi.core.SetVariable('AGI_RET_'+k, '&'.join([str(x) for x in result[k]])))
                  #for now only 1 level of nesting
                  elif type(result[k]) is dict:
                     ndict=result[k]
                     for nk in ndict:
                         if type(ndict[nk]) is list:
                             agi.execute(pystrix.agi.core.SetVariable('HASH(AGI_RET_'+k+','+nk+')', '&'.join([str(x) for x in ndict[nk]])))
                         else:
                             agi.execute(pystrix.agi.core.SetVariable('HASH(AGI_RET_'+k+','+nk+')', ndict[nk]))
                  else:
                      agi.execute(pystrix.agi.core.SetVariable('AGI_RET_'+k, result[k]))
            else:
                logger.debug('Dont have result')
        except:
                logger.exception('exception')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################

    #######################
    @wrapper
    def call_api_method_test(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            uniqueid = agi.execute(pystrix.agi.core.GetVariable('UNIQUEID'))
            muniqueid = agi.execute(pystrix.agi.core.GetVariable('MASTER_CHANNEL(UNIQUEID)'))
            logger.info('Start call_api_method for UNIQUEID=%s/%s'%(muniqueid,uniqueid))

            method_name = agi.execute(pystrix.agi.core.GetVariable('METHOD_NAME'))
            if method_name is None:
                logger.error('Error METHOD_NAME not set')
                return
            method_type = agi.execute(pystrix.agi.core.GetVariable('METHOD_TYPE'))
            if method_type is None:
                method_type = 'post'
            if method_type.lower() == 'get':
                method_type = 'get'
            else:
                method_type = 'post'

            logger.info('METHOD_NAME: %s METHOD_TYPE: %s'%(method_name, method_type))
            params={}
            params_str = agi.execute(pystrix.agi.core.GetVariable('METHOD_PARAMS'))
            if params_str is not None:
                for p in params_str.rsplit('-'):
                  params[p]=agi.execute(pystrix.agi.core.GetVariable(p))

            logger.info('params: %s',params)
            try:
                # Делаем запрос к API, передаем аргументы для запроса и задаем timeout
                start=time.time()
                if method_type == 'get':
                    ret = requests.get(TURL_TEST+method_name, params=params, timeout=2)
                else:
                    ret = requests.post(TURL_TEST+method_name, data=params, timeout=2)
                reqdur=time.time()-start
                FastAGIServer.thread_local.reqdur=reqdur
                logger.info('request dur: %d',reqdur*1000)
                logger.debug(ret)
            except:
                logger.exception('Exception while query taxiserv api')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'API_ERROR'))
                return

            data = ret.json()
            if data["data"]:
                result = data["data"]
                logger.debug('data: %s', result)
                ##interpret cdr specialy
                for k in result:
                  if k == 'cdr':
                     self.set_cdr(agi,result,logger)  
                  elif type(result[k]) is list:
                     agi.execute(pystrix.agi.core.SetVariable('AGI_RET_'+k, '&'.join([str(x) for x in result[k]])))
                  #for now only 1 level of nesting
                  elif type(result[k]) is dict:
                     ndict=result[k]
                     for nk in ndict:
                         if type(ndict[nk]) is list:
                             agi.execute(pystrix.agi.core.SetVariable('HASH(AGI_RET_'+k+','+nk+')', '&'.join([str(x) for x in ndict[nk]])))
                         else:
                             agi.execute(pystrix.agi.core.SetVariable('HASH(AGI_RET_'+k+','+nk+')', ndict[nk]))
                  else:
                      agi.execute(pystrix.agi.core.SetVariable('AGI_RET_'+k, result[k]))
            else:
                logger.debug('Dont have result')
        except:
                logger.exception('exception')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################

    #######################
    @wrapper
    def getphonebymask(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            uniqueid = agi.execute(pystrix.agi.core.GetVariable('UNIQUEID'))
            phone = agi.execute(pystrix.agi.core.GetVariable('EXTEN'))
            entry = agi.execute(pystrix.agi.core.GetVariable('agi_entry'))
            logging.debug('call uniqid: %s phone number: %s agi_entry: %s', uniqueid, phone, entry)
            if phone != None:
                # Создаем словарь с аргументами
                try:
                    # Создаем словарь с аргументами
                    args = {'phone': phone, 'entry': entry}
                    # Делаем запрос к API, передаем аргументы для запроса и задаем timeout
                    start=time.time()
                    r = requests.get(TURL+method, params=args, timeout=2)
                    reqdur=time.time()-start
                    FastAGIServer.thread_local.reqdur=reqdur
                    logger.info('request dur: %d',reqdur*1000)
                    data = r.json()
                    if data["data"]:
                        route = data["data"]
                        logger.debug('phone: %s have this result: %s', phone, route)
                    else:
                        logger.debug('phone: %s dont have result', phone)
                        return
                except:
                    logger.exception('phone: %s have exception while query taxiserv api', phone)
                    agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'API_ERROR'))
                    return

                if 'phone' in route:
                    agi.execute(pystrix.agi.core.SetVariable('__PHONE_HIDE_NUMBER', route['phone']))

        except:
                logger.exception('exception')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################

    #######################
    @wrapper
    def sipp_test(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        ##Set return status
        agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'OK'))

        try:
            time.sleep(0.2)
        except:
                logger.exception('exception')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################
   @wrapper
    def mixer(self, agi, args, kwargs, match, path, **kw):
        method=match.group(0)
        logger=kw['logger']
        mystr = agi.execute(pystrix.agi.core.GetVariable('HASH(rec,dialstr)'))
        result=mystr.split(',')
        random.shuffle(result)
        d=','.join(result)
        agi.execute(pystrix.agi.core.SetVariable("STR1",d))



        try:
            time.sleep(0.2)
        except:
                logger.exception('exception')
                agi.execute(pystrix.agi.core.SetVariable('AGI_STATUS', 'AGI_ERROR'))
    #######################




    def _noop_handler(self, agi, args, kwargs, match, path):
        """
        Does nothing, causing control to return to Asterisk's dialplan immediately; provided just
        to demonstrate the fallback handler.
        """

    def kill(self):
        self._fagi_server.shutdown()

    def run(self):
        self._fagi_server.serve_forever()



if __name__ == '__main__':
    fastagi_core = FastAGIServer()
    fastagi_core.start()

    while fastagi_core.is_alive():
        #In a larger application, you'd probably do something useful in another non-daemon
        #thread or maybe run a parallel AMI server
        time.sleep(1)
    fastagi_core.kill()
