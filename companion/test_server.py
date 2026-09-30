import copy,json,pathlib,threading,unittest,urllib.request
from unittest.mock import patch
from server import Hub,serve
from feed import episodes
class ServerTests(unittest.TestCase):
 def setUp(self):
  self.data=json.loads((pathlib.Path(__file__).parent/'fixtures/849845.json').read_text());self.data['gameData']['status'].update(abstractGameState='Live',detailedState='In Progress')
 def test_independent_display_clocks(self):
  h=Hub();t=1790704900;h.accept(self.data,t);h.for_client('one',t);h.for_client('two',t)
  e=dict(id='test-pitch',eventAt=t+1,inplay=False,scorers=[],duration=8,batter='HARPER',outcome='STRIKE')
  with patch('feed.episodes',return_value=[e]):
   h.accept(self.data,t+1)
   self.assertEqual(h.for_client('one',t+2)['episode']['age'],0)
   self.assertEqual(h.for_client('two',t+5)['episode']['age'],0)
   self.assertEqual(h.for_client('one',t+6)['episode']['age'],4)
 def test_http_boundary(self):
  h=Hub();server=serve(h,('127.0.0.1',0));threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   base='http://127.0.0.1:'+str(server.server_port)
   self.assertFalse(json.load(urllib.request.urlopen(base+'/health'))['ready'])
   self.assertFalse(json.load(urllib.request.urlopen(base+'/retro-baseball?consumer=test'))['active'])
   with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/retro-baseball?consumer=bad%20id')
   self.assertEqual(e.exception.code,400)
  finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()
