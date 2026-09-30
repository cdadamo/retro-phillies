import unittest,json,pathlib,copy
from feed import *
ROOT=pathlib.Path(__file__).parent
class ReplayTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((ROOT/'fixtures/776151.json').read_text());cls.today=json.loads((ROOT/'fixtures/849845.json').read_text());cls.events=episodes(cls.data)
 def test_full_game_runs_and_runner_names(self):
  self.assertEqual(sum(len(e['scorers']) for e in self.events),7)
  double=next(e for e in self.events if e['outcome']=='DOUBLE' and e['scorers'])
  self.assertEqual(double['batter'],'DURAN');self.assertEqual(double['scorers'],['SOGARD'])
  self.assertEqual((double['awayScore'],double['homeScore']),(3,4))
 def test_marker_missing_and_finite(self):
  self.assertIsNone(pitch_marker({}));self.assertIsNone(pitch_marker({'pitchData':{'coordinates':{'pX':float('nan'),'pZ':2},'strikeZoneTop':3,'strikeZoneBottom':1}}))
  self.assertEqual(number(1.0),1);self.assertEqual(number(float('nan')),0)
 def test_todays_start_and_focus(self):
  s=normalize(self.today);self.assertEqual(s['start'],'2:00');self.assertEqual((s['away'],s['home']),('PHI','ATL'));self.assertTrue(s['postseason'])
  f=LiveFeed();f.accept(self.today,s['kickoff']-30);self.assertFalse(f.payload(s['kickoff']-30)['active'])
 def test_no_old_replay_and_delayed_first_presentation(self):
  data=copy.deepcopy(self.data);data['gameData']['status']['abstractGameState']='Live';data['gameData']['status']['detailedState']='In Progress'
  end=stamp(data['liveData']['plays']['allPlays'][-1]['playEvents'][-1]['endTime'])
  f=LiveFeed();f.accept(data,end);self.assertNotIn('episode',f.payload(end,present=True))
  last=episodes(data)[-1];f.seen.remove(event_key(last));f.accept(data,end+1)
  p=f.payload(end+10,present=True);self.assertEqual(p['episode']['age'],0)
  self.assertEqual(f.payload(end+11,present=True)['episode']['age'],1)
  f.accept(data,end+12);self.assertEqual(f.payload(end+12,present=True)['episode']['age'],2)
  f.accept(data,end+200);self.assertNotIn('episode',f.payload(end+200,present=True))
 def test_final_hold_and_stale_release(self):
  data=copy.deepcopy(self.today);t=normalize(data)['kickoff']+60
  data['gameData']['status'].update(abstractGameState='Live',detailedState='In Progress')
  f=LiveFeed();f.accept(data,t);self.assertTrue(f.payload(t)['active']);self.assertEqual(f.payload(t+60)['mode'],'stale');self.assertTrue(f.payload(t+60)['active'])
  data['gameData']['status'].update(abstractGameState='Final',detailedState='Final');f.accept(data,t+70)
  self.assertTrue(f.payload(t+80)['active']);self.assertFalse(f.payload(t+971)['active']);self.assertFalse(f.payload(t+22000)['active'])
 def test_bases_and_integer_counts(self):
  for e in self.events:
   self.assertTrue(set(e['bases'])<={1,2,3})
   self.assertTrue(all(type(e[k]) is int for k in ['inning','balls','strikes','outs','awayScore','homeScore']))
   self.assertEqual(len(e['bases']),len(set(e['bases'])))
 def test_incomplete_inplay_waits_for_result(self):
  data=copy.deepcopy(self.data);play=next(p for p in data['liveData']['plays']['allPlays'] if any(e.get('details',{}).get('isInPlay') for e in p['playEvents']));data['liveData']['plays']['allPlays']=[play]
  lastid=next(e['playId'] for e in play['playEvents'] if e.get('details',{}).get('isInPlay'))
  play['about']['isComplete']=False;self.assertNotIn(lastid,[e['id'] for e in episodes(data)])
  play['about']['isComplete']=True;self.assertIn(lastid,[e['id'] for e in episodes(data)])
 def test_late_hit_result_is_new_and_finishes_before_next_pitch(self):
  from unittest.mock import patch
  e=copy.deepcopy(next(e for e in self.events if e['inplay']))
  t=e['eventAt'];data=copy.deepcopy(self.today)
  data['gameData']['status'].update(abstractGameState='Live',detailedState='In Progress')
  early=dict(e,inplay=False,outcome='',scorers=[],duration=8)
  following=dict(early,id='next-pitch',eventAt=t+12)
  f=LiveFeed()
  with patch('feed.episodes',return_value=[]):f.accept(data,t-1)
  with patch('feed.episodes',return_value=[early]):f.accept(data,t)
  self.assertFalse(f.payload(t,present=True)['episode']['inplay'])
  with patch('feed.episodes',return_value=[e]):f.accept(data,t+3)
  self.assertEqual(len(f.pending),1)
  self.assertTrue(f.payload(t+9,present=True)['episode']['inplay'])
  with patch('feed.episodes',return_value=[e,following]):f.accept(data,t+12)
  self.assertTrue(f.payload(t+13,present=True)['episode']['inplay'])
  self.assertEqual(f.payload(t+9+e['duration']+1,present=True)['episode']['id'],'next-pitch')
if __name__=='__main__':unittest.main()
