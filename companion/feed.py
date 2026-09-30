"""MLB replay adapter and bounded live state, no device writes."""
import copy,datetime,json,logging,math,pathlib,threading,time,unicodedata,urllib.request
from zoneinfo import ZoneInfo
EASTERN=ZoneInfo("America/New_York")
LOG=logging.getLogger('touchdown');API='https://statsapi.mlb.com';POSTSEASON={'F','D','L','W'}
def number(v,default=0):
 try:
  f=float(v);return int(f) if math.isfinite(f) and f.is_integer() else default
 except (ValueError,TypeError):return default
def name(s):return unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().upper()
def surname(s):return name(s.split()[-1] if s else '?')
def stamp(v):
 try:return datetime.datetime.fromisoformat(v.replace('Z','+00:00')).timestamp()
 except (ValueError,AttributeError):return 0

def pitch_marker(e):
 p=e.get('pitchData',{});c=p.get('coordinates',{});top=p.get('strikeZoneTop');bottom=p.get('strikeZoneBottom')
 try:
  px,pz,top,bottom=map(float,(c['pX'],c['pZ'],top,bottom))
  if not all(math.isfinite(v) for v in (px,pz,top,bottom)) or top<=bottom:return None
  # Catcher's perspective. Horizontal width is 17 inches; vertical uses batter-specific zone.
  return [max(35,min(61,round(46+px/(17/24)*4))),max(8,min(24,round(22-(pz-bottom)/(top-bottom)*10)))]
 except (KeyError,TypeError,ValueError):return None

def normalize(data):
 gd=data['gameData'];live=data.get('liveData',{});ls=live.get('linescore',{});plays=live.get('plays',{});cur=plays.get('currentPlay',{})
 teams=gd['teams'];status=gd.get('status',{});abstract=status.get('abstractGameState');detailed=status.get('detailedState','')
 mode={'Preview':'pre','Live':'live','Final':'final'}.get(abstract,'unavailable')
 if any(w in detailed.lower() for w in ('postpon','cancel','suspend')):mode='held'
 elif 'delay' in detailed.lower():mode='delay'
 offense=ls.get('offense',{});matchup=cur.get('matchup',{})
 batting='away' if ls.get('isTopInning',True) else 'home'
 dt=gd.get('datetime',{}).get('dateTime','');kickoff=stamp(dt)
 # zoneinfo is included in Alpine only if tzdata is available; explicit API local start is not used.
 local=datetime.datetime.fromtimestamp(kickoff,datetime.timezone.utc).astimezone(EASTERN) if kickoff else None
 out={'game':str(data.get('gamePk',gd.get('game',{}).get('pk',''))),'mode':mode,'detail':detailed,'kickoff':kickoff,'postseason':gd.get('game',{}).get('type') in POSTSEASON,'away':teams['away'].get('abbreviation','AWY'),'home':teams['home'].get('abbreviation','HME'),'awayScore':number(ls.get('teams',{}).get('away',{}).get('runs')),'homeScore':number(ls.get('teams',{}).get('home',{}).get('runs')),'inning':number(ls.get('currentInning'),1),'top':bool(ls.get('isTopInning',True)),'balls':number(ls.get('balls')),'strikes':number(ls.get('strikes')),'outs':number(ls.get('outs')),'bases':[i+1 for i,b in enumerate(('first','second','third')) if offense.get(b)],'batter':surname(offense.get('batter',matchup.get('batter',{})).get('fullName','')),'batSide':matchup.get('batSide',{}).get('code','R'),'batTeam':teams[batting].get('abbreviation','PHI'),'start':local.strftime('%I:%M').lstrip('0') if local else 'TBD','day':local.strftime('%a').upper() if local else '', 'markers':[pitch_marker(e) for e in cur.get('playEvents',[]) if e.get('isPitch') and pitch_marker(e) is not None]}
 return out

def episodes(data):
 """Reconstruct event state in sequence; never infer ball/strike from coordinates."""
 base=normalize(data);result=[];scores=[0,0];occupied={};half=None;outs=0
 for play in data.get('liveData',{}).get('plays',{}).get('allPlays',[]):
  about=play.get('about',{});halfkey=(about.get('inning'),about.get('isTopInning'))
  if halfkey!=half:occupied={};outs=0;half=halfkey
  balls=strikes=0;markers=[];matchup=play.get('matchup',{});batter=matchup.get('batter',{});before_play=scores[:]
  for e in play.get('playEvents',[]):
   index=e.get('index');moves=[r for r in play.get('runners',[]) if r.get('details',{}).get('playIndex')==index]
   before_bases=sorted(occupied);before_count=[balls,strikes,outs];before_scores=scores[:];runners=[];scorers=[]
   # Apply all departures before all arrivals, preventing overwrites when runners advance together.
   for r in moves:
    m=r.get('movement',{});start=m.get('start');start=number(str(start or '')[:1],0)
    if start:occupied.pop(start,None)
   for r in moves:
    m=r.get('movement',{});details=r.get('details',{});end=m.get('end');rid=details.get('runner',{});start=number(str(m.get('start') or '')[:1],0)
    if details.get('isScoringEvent') and not m.get('isOut'):
     scorers.append(surname(rid.get('fullName','')));scores[0 if about.get('isTopInning') else 1]+=1
    finish=4 if end=='score' else number(str(end or '')[:1],0)
    if finish in (1,2,3) and not m.get('isOut'):occupied[finish]=rid.get('id')
    if finish>start and not m.get('isOut'):runners.append([start,finish])
   c=e.get('count',{});balls=number(c.get('balls'),balls);strikes=number(c.get('strikes'),strikes);outs=number(c.get('outs'),outs)
   if not e.get('isPitch') and not moves:continue
   # Wait for the official outcome before emitting a ball-in-play episode.
   if e.get('details',{}).get('isInPlay') and not about.get('isComplete'):continue
   ep=dict(base);details=e.get('details',{});inplay=bool(details.get('isInPlay'));complete=about.get('isComplete',False)
   ep.update(id=str(e.get('playId') or f"{about.get('atBatIndex')}:{index}"),atBat=about.get('atBatIndex'),eventAt=stamp(e.get('endTime')),mode='live',inning=number(about.get('inning'),1),top=bool(about.get('isTopInning')),batter=surname(batter.get('fullName','')),batSide=matchup.get('batSide',{}).get('code','R'),batTeam=base['away'] if about.get('isTopInning') else base['home'],balls=balls,strikes=strikes,outs=outs,beforeCount=before_count,bases=sorted(occupied),beforeBases=before_bases,awayScore=scores[0],homeScore=scores[1],beforeScores=before_scores,marker=pitch_marker(e),markers=markers[:],isPitch=bool(e.get('isPitch')),inplay=inplay,swing=details.get('code') in ('S','W','T','F','L','M','Q') or inplay,scorers=scorers,runners=runners,hit=e.get('hitData',{}),call='IN PLAY' if inplay else 'BALL' if details.get('isBall') else 'FOUL' if 'foul' in details.get('description','').lower() else 'STRIKE' if details.get('isStrike') else 'PLAY',outcome=name(play.get('result',{}).get('event','')) if complete and (inplay or balls>=4 or strikes>=3) else name(details.get('event','')))
   if pitch_marker(e) is not None:markers.append(pitch_marker(e))
   if ep['outcome']=='STRIKEOUT':ep['call']='STRIKE'
   ep['duration']=(8 if ep['isPitch'] else 0)+(6 if inplay and complete else 0)+4*len(scorers)+(3 if ep['outcome'] and not inplay else 0)
   ep['duration']=max(3,ep['duration']);result.append(ep)
  if about.get('isComplete'):
   scores=[number(play.get('result',{}).get('awayScore'),scores[0]),number(play.get('result',{}).get('homeScore'),scores[1])]
 return result

def event_key(e):
 # MLB can publish the pitch before attaching its final hit/outcome.
 return e['id']+(':result' if e['inplay'] else ':pitch')

class LiveFeed:
 def __init__(self):
  self.snapshot=None;self.seen=set();self.game=None;self.episode=None;self.started=0;self.presented=False;self.last=0;self.final_at=0;self.pending=[];self.lock=threading.RLock();self.recent=[]
 def _select(self,e,now):
  self.episode=e;self.started=now;self.presented=False
 def accept(self,data,now=None):
  with self.lock:self._accept(data,time.time() if now is None else now)
 def _accept(self,data,now):
  snapshot=normalize(data);items=episodes(data);ids={event_key(p) for p in items}
  if self.game!=snapshot['game'] or not self.last or now-self.last>180:
   self.seen=ids;self.episode=None;self.pending=[];self.final_at=0
  else:
   new=[p for p in items if event_key(p) not in self.seen and p['eventAt'] and -30<=now-p['eventAt']<=300]
   for e in new:
    self.recent.append({'batter':e['batter'],'key':event_key(e),'outcome':e['outcome'],'lag':round(now-e['eventAt'],1)})
    self.recent=self.recent[-12:]
    busy=self.episode and ((self.presented and now-self.started<self.episode['duration']) or (not self.presented and now-self.started<120))
    if self.episode and not self.presented and self.episode['id']==e['id']:
     self._select(e,now)
    else:
     # Coalesce ordinary pitches, but preserve completed hits/scoring until shown.
     self.pending=[p for p in self.pending if p['inplay'] or p['scorers']]
     self.pending.append(e);self.pending=self.pending[-4:]
     if not busy:self._select(self.pending.pop(0),now)
   if snapshot['mode']=='final' and self.snapshot and self.snapshot['mode'] in ('live','delay') and not self.final_at:self.final_at=now
  self.game=snapshot['game'];self.snapshot=snapshot;self.seen.update(ids);self.last=now
 def payload(self,now=None,present=False):
  with self.lock:return self._payload(time.time() if now is None else now,present)
 def _payload(self,now,present):
  if self.snapshot is None:return {'mode':'unavailable','active':False,'ageSeconds':9999}
  s=dict(self.snapshot);age=max(0,now-self.last);s.update(ageSeconds=int(age),finalAt=self.final_at)
  live=s['mode'] in ('live','delay');s['active']=s['postseason'] and (live or (s['mode']=='final' and 0<self.final_at and now-self.final_at<900)) and -300<=now-s['kickoff']<21600
  s['inGameWindow']=(live or (s['mode']=='final' and 0<self.final_at and now-self.final_at<900)) and -300<=now-s['kickoff']<21600
  if age>45 and live:s['mode']='stale'
  if age>21600:s['active']=False;s['inGameWindow']=False;s['mode']='unavailable'
  if present and self.pending and (not self.episode or (self.presented and now-self.started>=self.episode['duration']) or now-self.started>=120):
   self._select(self.pending.pop(0),now)
  if self.episode and not self.presented and present and now-self.started<120:
   self.started=now;self.presented=True
  if self.episode and self.presented and now-self.started<self.episode['duration'] and s['mode'] in ('live','final'):s['episode']=dict(self.episode,age=max(0,now-self.started))
  return s

def fetch(url):
 with urllib.request.urlopen(url,timeout=12) as r:return json.load(r)
def run(feed):
 schedule=[];next_schedule=0
 while True:
  delay=60
  try:
   now=time.time()
   if now>=next_schedule:
    today=datetime.datetime.now(EASTERN).date()
    board=fetch(API+'/api/v1/schedule?sportId=1&teamId=143&startDate='+str(today-datetime.timedelta(days=1))+'&endDate='+str(today+datetime.timedelta(days=1)))
    schedule=[g for d in board.get('dates',[]) for g in d.get('games',[])];next_schedule=now+60
   live=[g for g in schedule if g['status'].get('abstractGameState')=='Live']
   upcoming=sorted([g for g in schedule if g['status'].get('abstractGameState')=='Preview'],key=lambda g:g['gameDate'])
   finals=sorted([g for g in schedule if g['status'].get('abstractGameState')=='Final'],key=lambda g:g['gameDate'],reverse=True)
   # Retain current game for its final hold before switching to the next matchup.
   held=next((g for g in schedule if str(g['gamePk'])==feed.game and ((feed.final_at and now-feed.final_at<900) or (feed.snapshot and feed.snapshot['mode'] in ('live','delay') and now-feed.snapshot['kickoff']<21600))),None)
   game=(live[:1] or ([held] if held else []) or upcoming[:1] or finals[:1])
   if game:
    data=fetch(API+'/api/v1.1/game/'+str(game[0]['gamePk'])+'/feed/live');feed.accept(data)
    g=game[0];feed.snapshot.update(seriesLabel={'F':'WILD CARD','D':'DIV SERIES','L':'LCS','W':'WORLD SERIES'}.get(g.get('gameType'),'PREGAME'),gameLabel='GAME '+str(g.get('seriesGameNumber',1)))
    s=feed.payload();delay=5 if s['mode'] in ('live','delay') or abs(now-s['kickoff'])<900 else 60
   LOG.info('Retro MLB feed: %s',feed.payload().get('mode')) if feed.snapshot is None else None
  except Exception as e:LOG.warning('Retro MLB feed failed (%s)',type(e).__name__);delay=10
  time.sleep(delay)
def start():
 feed=LiveFeed();threading.Thread(target=run,args=(feed,),daemon=True).start();return feed
