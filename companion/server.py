"""Public-data-only companion. No Tronbyt credentials or device control."""
import copy,json,os,re,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from feed import LiveFeed,run

class Hub(LiveFeed):
 def __init__(self):
  super().__init__();self.raw=None;self.clients={}
 def accept(self,data,now=None):
  with self.lock:
   super().accept(data,now);self.raw=data
 def for_client(self,key,now=None):
  now=time.time() if now is None else now
  with self.lock:
   if self.raw is None:return self.payload(now)
   self.clients={k:v for k,v in self.clients.items() if now-v[1]<3600}
   if key not in self.clients:
    if len(self.clients)>=32:raise ValueError('Too many display IDs')
    self.clients[key]=(LiveFeed(),now)
   client,_=self.clients[key];self.clients[key]=(client,now)
   if client.last!=self.last:
    client.accept(self.raw,self.last)
    for field in ['seriesLabel','gameLabel']:
     if field in self.snapshot:client.snapshot[field]=self.snapshot[field]
   return client.payload(now,present=True)

def serve(hub,address=('0.0.0.0',8767)):
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   parsed=urlsplit(self.path)
   if parsed.path=='/health':payload={'ready':hub.snapshot is not None,'ageSeconds':int(time.time()-hub.last) if hub.last else None}
   elif parsed.path=='/retro-baseball':
    key=parse_qs(parsed.query).get('consumer',['display1'])[0]
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',key):self.send_error(400,'Invalid display ID');return
    try:payload=hub.for_client(key)
    except ValueError:self.send_error(429,'Too many display IDs');return
   else:self.send_error(404);return
   data=json.dumps(payload).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
  def log_message(self,*args):pass
 return ThreadingHTTPServer(address,Handler)

if __name__=='__main__':
 import logging
 logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
 hub=Hub();threading.Thread(target=run,args=(hub,),daemon=True).start()
 serve(hub,(os.getenv('BIND_ADDRESS','0.0.0.0'),int(os.getenv('PORT','8767')))).serve_forever()
