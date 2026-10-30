"""Explicit QA fault injection on fresh isolated labs; always stop owned nodes."""
import argparse
from datetime import datetime
from pathlib import Path
from netlab.recipes import make_catalog_plan
from netlab.wizard import connector_from_record, deploy_plan, save_json

p=argparse.ArgumentParser();p.add_argument('cases',nargs='+',choices=['B04','I03','A05','A07']);p.add_argument('--host',required=True);p.add_argument('--control',required=True);p.add_argument('--guest-id',type=int);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
record=dict(host=a.host,user='root',control=a.control,backend='gns3' if a.guest_id else 'eve')
if a.guest_id:record.update(transport='qga',guest_id=a.guest_id)
c=connector_from_record(record,batch=True);a.output.mkdir(parents=True,exist_ok=False);summary=[]
def observe(plan, exercise, out, label, ports):
 try:return c.run('verify',plan=plan,ports=ports,exercise=exercise)
 except RuntimeError as exc:
  save_json(out/(label+'-first-error.json'),{'error':str(exc),'read_only_retry':True})
  print('Retrying read-only observation',label,flush=True)
  return c.run('verify',plan=plan,ports=ports,exercise=exercise)

for sid in a.cases:
 plan=make_catalog_plan(sid,'nlf-fault-'+sid.lower()+'-'+datetime.now().strftime('%m%d%H%M%S'),backend=record['backend'],mode='reference',folder='Network-Lab-Factory/Catalog-QA')
 out=a.output/sid.lower();events=[];changed=False
 try:
  print('BEGIN',sid,flush=True);r=deploy_plan(c,plan,out,callback=events.append)
  if r['status']!='ready':raise RuntimeError('Baseline must pass before injecting a fault')
  changed=True;save_json(out/'fault-action.json',c.run('fault',plan=plan,ports=r['ports']))
  fault=observe(plan,True,out,'fault',r['ports']);save_json(out/'fault-check.json',fault)
  pings=[x for x in fault['checks'] if x['kind']=='ping'];protocols=[x for x in fault['checks'] if x['kind']=='regex']
  expected=(all(not x['passed'] for x in pings) if sid=='A07' else all(x['passed'] for x in pings)) and any(not x['passed'] for x in protocols)
  save_json(out/'restore-action.json',c.run('restore',plan=plan,ports=r['ports']));changed=False
  base=observe(plan,False,out,'restore-base',r['ports']);exercise=observe(plan,True,out,'restore-exercise',r['ports'])
  save_json(out/'restored-base.json',base);save_json(out/'restored-exercise.json',exercise)
  passed=expected and base['status']==exercise['status']=='passed'
  summary.append({'scenario':sid,'status':'passed' if passed else 'failed','expected_fault_observed':expected,'directory':str(out)})
 except Exception as exc:
  summary.append({'scenario':sid,'status':'incomplete','reason':str(exc),'directory':str(out)})
 finally:
  if any(e.get('event')=='created' for e in events):
   if changed:
    try:save_json(out/'cleanup-restore.json',c.run('restore',plan=plan,ports={e['node']:e['port'] for e in events if e.get('event')=='started'}))
    except RuntimeError:pass
   save_json(out/'stopped.json',c.run('stop',plan=plan))
  save_json(a.output/'summary.json',summary)
 print('END',sid,summary[-1]['status'],flush=True)
