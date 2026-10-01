"""UI validation tests with synthetic inputs and fake widgets; no desktop or auth."""
from types import SimpleNamespace
import unittest
import secrets
from unittest.mock import patch
import recovery_gui as gui

TEST_PASSWORD = secrets.token_urlsafe(24)
OTHER_PASSWORD = secrets.token_urlsafe(24)
UNICODE_PASSWORD = "ダミー専用" + secrets.token_urlsafe(24)

class Widget:
    def __init__(self,text=''): self.text,self.sensitive=text,True
    def get_text(self): return self.text
    def set_text(self,text): self.text=text
    def set_sensitive(self,value): self.sensitive=value

class ValidationTests(unittest.TestCase):
    def window(self,password,confirm):
        fields={k:Widget(v) for k,v in {'password':password,'confirm':confirm,'env':'/synthetic/input','auth':'','output':'/synthetic/output'}.items()}
        fields.update({'feedback':Widget(),'button':Widget()})
        window=SimpleNamespace(busy=False,status=Widget(),notebook=Widget(),passwords=[fields['password'],fields['confirm']])
        window._update_password_feedback=lambda event,f,s: gui.RecoveryWindow._update_password_feedback(window,event,f,s)
        window._update_password_feedback(None,fields,True)
        return window,fields

    def test_empty_short_and_mismatch_disable_save(self):
        for password,confirm in [('', ''),('synthetic-short','synthetic-short'),(TEST_PASSWORD,OTHER_PASSWORD)]:
            with self.subTest(length=len(password)):
                window,fields=self.window(password,confirm)
                self.assertFalse(fields['button'].sensitive)
                self.assertTrue(fields['feedback'].text)
                if password: self.assertNotIn(password,fields['feedback'].text)

    def test_valid_matching_input_enables_save(self):
        window,fields=self.window(TEST_PASSWORD,TEST_PASSWORD)
        self.assertTrue(fields['button'].sensitive)
        self.assertIn('入力条件を満たしています',fields['feedback'].text)

    def test_local_failure_preserves_both_entries(self):
        for password,confirm in [('', ''),('synthetic-short','synthetic-short'),(TEST_PASSWORD,OTHER_PASSWORD)]:
            window,fields=self.window(password,confirm)
            with patch.object(gui,'backup') as save:
                gui.RecoveryWindow._run(window,None,fields,True)
                save.assert_not_called()
            self.assertEqual(fields['password'].text,password)
            self.assertEqual(fields['confirm'].text,confirm)

    def test_invalid_path_preserves_password(self):
        window,fields=self.window(TEST_PASSWORD,TEST_PASSWORD)
        fields['output'].set_text('relative')
        with patch.object(gui,'backup') as save:
            gui.RecoveryWindow._run(window,None,fields,True)
            save.assert_not_called()
        self.assertEqual(fields['password'].text,TEST_PASSWORD)
        self.assertIn('絶対パス',window.status.text)

    def test_success_clears_entries_and_disables_repeat(self):
        window,fields=self.window(TEST_PASSWORD,TEST_PASSWORD)
        with patch.object(gui,'backup',return_value=True) as save:
            gui.RecoveryWindow._run(window,None,fields,True)
            save.assert_called_once()
        self.assertEqual(fields['password'].text,'')
        self.assertEqual(fields['confirm'].text,'')
        self.assertFalse(fields['button'].sensitive)
        self.assertIn('保存しました',window.status.text)

    def test_operation_failure_clears_entries_safely(self):
        window,fields=self.window(TEST_PASSWORD,TEST_PASSWORD)
        with patch.object(gui,'backup',side_effect=OSError('not shown')):
            gui.RecoveryWindow._run(window,None,fields,True)
        self.assertEqual(fields['password'].text,'')
        self.assertFalse(fields['button'].sensitive)
        self.assertNotIn('not shown',window.status.text)

    def test_whitespace_only_and_oversize_are_rejected(self):
        for password in [' '*16,'x'*1025]:
            self.assertFalse(gui.password_feedback(password,password)[0])

    def test_unicode_length_accepted(self):
        self.assertTrue(gui.password_feedback(UNICODE_PASSWORD,UNICODE_PASSWORD)[0])

if __name__=='__main__': unittest.main(verbosity=2)
