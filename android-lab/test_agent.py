import os,unittest,importlib.util,io,json
from pathlib import Path
from unittest.mock import patch
os.environ.update(LAB_RELAY='https://example.invalid',GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1')
spec=importlib.util.spec_from_file_location('agent',Path(__file__).with_name('agent.py'));agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
class AgentContracts(unittest.TestCase):
 def test_result_outage_never_repeats_the_action_or_leases_another(self):
  calls={'take':0,'execute':0,'send':0};sent=[]
  def take():calls['take']+=1;return {'id':'one'}
  def execute(command):calls['execute']+=1;return {'saved':True}
  def send(result):
   calls['send']+=1;sent.append(result)
   if calls['send']==1:raise OSError('connection lost after execution')
  pending=agent.control_tick(None,take,execute,send)
  self.assertEqual(calls['execute'],1);self.assertIsNotNone(pending)
  self.assertIsNone(agent.control_tick(pending,take,execute,send));self.assertEqual(calls,{'take':1,'execute':1,'send':2});self.assertEqual(sent[0],sent[1])
 def test_failed_action_is_reported_without_becoming_pass(self):
  sent=[]
  def execute(command):raise ValueError('synthetic failure')
  self.assertIsNone(agent.control_tick(None,lambda:{'id':'one'},execute,sent.append));self.assertEqual(sent[0]['state'],'failed')
 def test_screen_edges_are_inside_display(self):
  self.assertEqual(agent.screen_point(1,1236),1235);self.assertEqual(agent.screen_point(0,2745),0)
 def test_webdriver_marks_all_payloads_sensitive(self):
  seen=[]
  class Response(io.BytesIO):
   def __enter__(self):return self
   def __exit__(self,*args):self.close()
  def open_request(request,**kwargs):seen.append(request);return Response(b'{"value":{}}')
  with patch.object(agent.urllib.request,'urlopen',open_request):agent.wd('POST','/session/x/element/y/value',{'text':'private input'})
  self.assertEqual(seen[0].get_header('X-appium-is-sensitive'),'true')
 def test_samsung_geometry_is_fixed_and_cannot_execute_caller_text(self):
  calls=[]
  with patch.object(agent,'adb',lambda *args:calls.append(args)):
   agent.set_profile('s24-ultra')
   self.assertEqual((agent.WIDTH,agent.HEIGHT,agent.DENSITY),(1440,3120,560))
   self.assertEqual(calls,[('shell','wm','size','1440x3120'),('shell','wm','density','560')])
   with self.assertRaises(ValueError):agent.set_profile('1440;reboot')
   agent.set_profile('alpha-main')
if __name__=='__main__':unittest.main()
