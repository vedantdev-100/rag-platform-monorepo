"""Opt-in live API acceptance; creates a fixture document and two chats.

Use a dedicated account. Prompts for tokens without echoing them. Leaves fixtures
for inspection; prints their IDs. Provider calls consume your configured quota.
"""
import argparse
import getpass
import json
import time
import uuid
import httpx

FIXTURE = b'Atlas is owned by Mira. Mira took ownership of Atlas on 15 January 2025. The project launch date is 20 February 2025.\n'

def expect(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f'Unexpected HTTP {response.status_code}; expected {status}; inspect backend logs using the request ID')
    return response.json() if response.content else None

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--isolation',action='store_true',help='Prompt for another test user token and verify isolation')
    args=parser.parse_args()
    token=getpass.getpass('Dedicated test account Bearer access token: ').strip()
    if not token: raise SystemExit('A token is required')
    with httpx.Client(base_url=args.base_url.rstrip('/'),headers={'Authorization':f'Bearer {token}'},timeout=180) as client:
        doc=expect(client.post('/api/v1/documents',files={'file':('chat_acceptance.txt',FIXTURE,'text/plain')}),202)
        did=doc['id'];print('Fixture document ID:',did)
        deadline=time.monotonic()+300
        while True:
            state=expect(client.get(f'/api/v1/documents/{did}'))
            if state['status']=='ingested': break
            if state['status']=='failed' or time.monotonic()>deadline: raise RuntimeError('Fixture ingestion did not complete')
            time.sleep(2)
        chat=expect(client.post('/api/v1/conversations',json={'title':'Chat acceptance fixture'}),201);cid=chat['id']
        print('Fixture conversation ID:',cid)
        expect(client.put(f'/api/v1/conversations/{cid}/documents',json={'document_scope':'selected','document_ids':[did]}))
        first={'query':'Who owns Atlas?','top_k':5,'client_message_id':str(uuid.uuid4())}
        response=client.post(f'/api/v1/conversations/{cid}/messages/stream',json=first)
        if response.status_code != 200: expect(response)
        events=[]
        for block in response.text.split('\n\n'):
            name=None;data=[]
            for line in block.splitlines():
                if line.startswith('event: '): name=line[7:]
                elif line.startswith('data: '): data.append(line[6:])
            if name and data: events.append((name,json.loads('\n'.join(data))))
        if not events or events[-1][0]!='done': raise RuntimeError('Stream did not end successfully')
        answer=events[-1][1]['messages'][1]['answer']
        assert 'mira' in answer['answer'].lower() and answer['sources']
        replay=expect(client.post(f'/api/v1/conversations/{cid}/messages',json=first))
        assert replay['replay'] and replay['status']=='completed'
        second={'query':'When did she take ownership?','client_message_id':str(uuid.uuid4())}
        result=expect(client.post(f'/api/v1/conversations/{cid}/messages',json=second))
        text=result['messages'][1]['content'].lower()
        assert '2025' in text and ('january' in text or '01-15' in text or '15/01' in text), 'Follow-up answer needs review'
        history=expect(client.get(f'/api/v1/conversations/{cid}/messages'))['items']
        assert len(history)==4 and all(m['status']=='completed' for m in history)
        source=answer['sources'][0]
        expect(client.get(f"/api/v1/documents/{source['document_id']}/chunks/{source['chunk_id']}"))
        empty=expect(client.post('/api/v1/conversations',json={'title':'Empty selected scope fixture'}),201)
        print('Empty-scope conversation ID:',empty['id'])
        abstain=expect(client.post(f"/api/v1/conversations/{empty['id']}/messages",json={
            'query':'Who owns Atlas?','client_message_id':str(uuid.uuid4())}))
        assert abstain['messages'][1]['answer']['status']=='insufficient_context'
        if args.isolation:
            other=getpass.getpass('Different test user Bearer access token: ').strip()
            headers={'Authorization':f'Bearer {other}'}
            expect(client.get(f'/api/v1/conversations/{cid}',headers=headers),404)
            foreign_chat=expect(client.post('/api/v1/conversations',json={'title':'Isolation fixture'},headers=headers),201)
            response=client.put(f"/api/v1/conversations/{foreign_chat['id']}/documents",
                               json={'document_ids':[did]},headers=headers)
            expect(response,404)
            expect(client.get(f"/api/v1/documents/{did}/chunks/{source['chunk_id']}",headers=headers),404)
            expect(client.delete(f"/api/v1/conversations/{foreign_chat['id']}",headers=headers),204)
        print('Chat live API acceptance: PASSED. Fixtures retained for inspection.')

if __name__=='__main__': main()
