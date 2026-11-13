"""Owner-bound durable continuation leases; stores data, never capabilities."""
import json
import time
from uuid import uuid4


class Continuations:
    def __init__(self,store,clock=time.time):
        self.store,self.clock = store,clock

    @staticmethod
    def _encode(value):
        encoded = json.dumps(value,allow_nan=False,sort_keys=True)
        if len(encoded.encode())>2097152:
            raise ValueError('Continuation data too large')
        return encoded

    def start(self,user_id,binding,state):
        if type(user_id) is not int or user_id<=0:
            raise ValueError('Authenticated owner required')
        key = str(uuid4())
        payload = dict(binding=binding,state=state,attempts=0,lease=None,replays={})
        encoded = self._encode(payload)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE analytics_continuations SET expires_at=0 WHERE user_id=?',(user_id,))
            db.execute('INSERT INTO analytics_continuations VALUES (?,?,?,0,?)',(key,user_id,self.clock()+600,encoded))
        return key

    def claim(self,user_id,key,binding,action_id):
        if not isinstance(action_id,str) or not 1<=len(action_id)<=100:
            raise ValueError('Continuation action required')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT expires_at,payload FROM analytics_continuations WHERE id=? AND user_id=?',(key,user_id)).fetchone()
            if not row or row[0]<=self.clock():
                raise ValueError('Continuation expired or unavailable')
            payload = json.loads(row[1])
            if payload['binding'] != binding:
                raise ValueError('Evidence context changed; start a fresh run')
            if action_id in payload['replays']:
                return dict(replay=payload['replays'][action_id], state=payload['state'])
            if payload['lease'] and payload['lease']['until']>self.clock():
                raise ValueError('Continuation already running')
            if payload['attempts']>=2:
                raise ValueError('Continuation budget exhausted')
            payload['attempts'] += 1
            payload['lease'] = dict(action_id=action_id,until=self.clock()+35,nonce=str(uuid4()))
            db.execute('UPDATE analytics_continuations SET revision=revision+1,payload=? WHERE id=? AND user_id=?',
                       (self._encode(payload),key,user_id))
        return dict(state=payload['state'],attempt=payload['attempts'],lease_nonce=payload['lease']['nonce'])

    def finish(self,user_id,key,action_id,lease_nonce,state,response):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT expires_at,payload FROM analytics_continuations WHERE id=? AND user_id=?',(key,user_id)).fetchone()
            if not row or row[0]<=self.clock():
                raise ValueError('Continuation expired or unavailable')
            payload = json.loads(row[1])
            lease = payload['lease']
            if not lease or lease['action_id']!=action_id or lease['nonce']!=lease_nonce or lease['until']<=self.clock():
                raise ValueError('Continuation lease expired')
            payload.update(state=state,lease=None)
            payload['replays'][action_id] = response
            db.execute('UPDATE analytics_continuations SET revision=revision+1,payload=? WHERE id=? AND user_id=?',
                       (self._encode(payload),key,user_id))
