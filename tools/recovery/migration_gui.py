#!/usr/bin/python3
"""One-time user-operated setup. No password arguments or environment input."""
import argparse
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from recovery_gui import password_feedback
from recovery_core import RecoveryError
from migration import load_plan,setup_state

class SetupWindow(Gtk.Window):
 def __init__(self,plan):
  super().__init__(title='Discord Bot 自動バックアップ準備')
  self.plan=plan;self.busy=False;self.new_setup=plan["existing_backup_path"] is None
  self.set_border_width(24);self.set_default_size(720,360)
  box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16);self.add(box)
  note=Gtk.Label(xalign=0);note.set_line_wrap(True)
  note.set_text('既存の復旧用パスワードを1回入力してください。\n新しい暗号化鍵を作り、復旧用の秘密鍵はこのパスワードで暗号化して保存します。\n以後の暗号化には公開鍵だけを使い、パスワードは保存しません。\nこの操作では Bot の設定・認証を読み、新方式の初回バックアップをローカルに作ります。\nLibrary保存と監視の有効化は、準備成功後に確認して開始します。')
  if self.new_setup:
   self.set_title('初回・自動バックアップ設定')
   note.set_text('初回から自動バックアップを設定します。\n新しい復旧用パスワードと確認を入力してください。手動バックアップを先に作る必要はありません。\n復旧用秘密鍵をこのパスワードで暗号化し、以後は公開鍵だけで自動暗号化します。\nパスワードは保存しません。Library保存と監視は準備後に有効化します。')
  box.pack_start(note,False,False,0)
  self.entry=Gtk.Entry();self.entry.set_visibility(False);self.entry.set_invisible_char('●');self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD);self.entry.set_max_length(1024)
  box.pack_start(self.entry,False,False,0)
  self.confirm=None
  if self.new_setup:
   self.entry.set_placeholder_text('新しい復旧用パスワード（16文字以上）')
   self.confirm=Gtk.Entry();self.confirm.set_visibility(False);self.confirm.set_invisible_char('●');self.confirm.set_input_purpose(Gtk.InputPurpose.PASSWORD);self.confirm.set_max_length(1024);self.confirm.set_placeholder_text('確認のため同じパスワードを入力')
   box.pack_start(self.confirm,False,False,0)
  self.hint=Gtk.Label(xalign=0);self.hint.set_line_wrap(True);box.pack_start(self.hint,False,False,0)
  self.button=Gtk.Button(label='このパスワードで自動バックアップを準備する');self.button.connect('clicked',self.run_setup);box.pack_start(self.button,False,False,0)
  self.status=Gtk.Label(xalign=0);self.status.set_line_wrap(True);box.pack_start(self.status,False,False,0)
  self.entry.connect('changed',self.update)
  if self.confirm is not None:self.confirm.connect('changed',self.update)
  self.connect('destroy',self.close)
  self.update();self.show_all();self.entry.grab_focus()
 def update(self,*_):
  valid,message=password_feedback(self.entry.get_text(),self.confirm.get_text() if self.confirm is not None else None);self.hint.set_text(message);self.button.set_sensitive(valid and not self.busy)
 def close(self,*_):
  self.entry.set_text('')
  if self.confirm is not None:self.confirm.set_text('')
  Gtk.main_quit()
 def run_setup(self,*_):
  if self.busy:return
  password=self.entry.get_text();valid,message=password_feedback(password,self.confirm.get_text() if self.confirm is not None else None)
  if not valid:self.status.set_text(message);return
  self.busy=True;self.button.set_sensitive(False);self.entry.set_sensitive(False)
  try:
   result=setup_state(self.plan,password)
   self.status.set_text('初回バックアップと復元確認が完了しました。監視とLibrary保存の有効化を確認してください。この画面は閉じます。' if result['durability_confirmed'] else '準備は保存されましたが、ディスクへの確定保存を確認できませんでした。')
   GLib.timeout_add(2000,self.destroy)
  except RecoveryError as error:
   known={'Wrong recovery passphrase or damaged backup. Nothing was restored.':'既存の復旧用パスワードが違うか、元のバックアップが破損しています。',
          'Destination already exists. Choose a new name; existing data is never overwritten.':'準備先はすでに存在します。上書きは行いません。'}
   self.status.set_text('準備できませんでした: '+known.get(str(error),'設定ファイルまたは保存先を確認してください。'))
  except Exception:self.status.set_text('準備できませんでした。設定ファイルと保存先を確認してください。秘密情報の詳細ログは保存しません。')
  finally:
   password=None;self.entry.set_text('')
   if self.confirm is not None:self.confirm.set_text('')
   self.busy=False;self.entry.set_sensitive(True);self.update()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);args=parser.parse_args()
 try:plan=load_plan(args.plan)
 except Exception:raise SystemExit('Setup plan is unavailable or invalid; no secret diagnostics emitted.')
 if not Gtk.init_check()[0]:raise SystemExit('Open this helper on a Linux desktop with GTK 3.')
 SetupWindow(plan);Gtk.main()
