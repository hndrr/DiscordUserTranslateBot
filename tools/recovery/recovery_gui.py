#!/usr/bin/python3
"""Local masked-password UI. No secrets in CLI arguments or application logs."""
from pathlib import Path
import sys
import tempfile

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from recovery_core import RecoveryError, backup, restore, _password


def password_feedback(password, confirm=None):
    """Return only validity and nonsecret Japanese guidance, never input text."""
    length = len(password)
    if length < 16:
        return False, f"復旧用パスワードは現在{length}文字です。16文字以上にしてください。"
    if length > 1024:
        return False, "復旧用パスワードは1024文字以内にしてください。"
    try:
        _password(password)
    except RecoveryError:
        return False, "空白だけのパスワードは使えません。別の長いパスフレーズを入力してください。"
    if confirm is not None and password != confirm:
        return False, f"復旧用パスワードは{length}文字です。確認欄にも同じものを入力してください。"
    return True, f"復旧用パスワードは{length}文字です。入力条件を満たしています。"


class RecoveryWindow(Gtk.Window):
    def __init__(self, dummy=False):
        super().__init__(title="Discord Bot 復旧" + (" — ダミーテスト専用" if dummy else ""))
        self.set_default_size(700, 550)
        self.set_border_width(20)
        self.connect("destroy", self._close)
        self.busy = False
        self.dummy = dummy
        self.passwords = []
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(outer)
        title = Gtk.Label(label="Discord Bot の暗号化バックアップ・復元", xalign=0)
        outer.pack_start(title, False, False, 0)
        info = Gtk.Label(xalign=0)
        info.set_line_wrap(True)
        info.set_text("この画面は実行中の Linux デスクトップ上です。パスワードは伏せ字で入力し、保存しません。\n復元は新しいフォルダに保存します。既存設定の上書きや Bot の起動は行いません。" +
                      ("\nダミーテスト専用。本物の認証情報は選択・入力しないでください。" if dummy else ""))
        outer.pack_start(info, False, False, 0)
        notebook = Gtk.Notebook()
        self.notebook = notebook
        outer.pack_start(notebook, True, True, 0)
        self.backup_fields = self._page(notebook, True)
        self.restore_fields = self._page(notebook, False)
        if dummy:
            demo_parent = Path(__file__).parent / "dummy-demo"
            demo_parent.mkdir(mode=0o700, exist_ok=True)
            self.demo_root = Path(tempfile.mkdtemp(prefix="DUMMY-ONLY-", dir=demo_parent))
            (self.demo_root / "DUMMY-env").write_bytes(b"DISCORD_TOKEN=DUMMY_NOT_A_REAL_TOKEN\nAI_PROVIDER=codex\n")
            (self.demo_root / "DUMMY-auth").write_bytes(b'{"dummy_only":true,"token":"DUMMY_AUTH_REVISION_1"}\n')
            values = [(self.backup_fields, {"env": "DUMMY-env", "auth": "DUMMY-auth", "output": "DUMMY-backup.encrypted.json"}),
                      (self.restore_fields, {"input": "DUMMY-backup.encrypted.json", "output": "DUMMY-restored"})]
            for fields, names in values:
                for key, name in names.items():
                    fields[key].set_text(str(self.demo_root / name))
                    fields[key].set_editable(False)
                    if key + "_choose" in fields:
                        fields[key + "_choose"].set_sensitive(False)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_selectable(False)
        outer.pack_start(self.status, False, False, 0)
        close = Gtk.Button(label="閉じる")
        close.connect("clicked", lambda _: self.destroy())
        outer.pack_start(close, False, False, 0)
        self.show_all()

    def _close(self, *_):
        for entry in self.passwords:
            entry.set_text("")
        Gtk.main_quit()

    def _choose(self, _, entry, action):
        chooser = Gtk.FileChooserDialog(title="ファイルを選ぶ", transient_for=self, action=action)
        chooser.add_buttons("キャンセル", Gtk.ResponseType.CANCEL, "選択", Gtk.ResponseType.OK)
        if chooser.run() == Gtk.ResponseType.OK:
            entry.set_text(chooser.get_filename())
        chooser.destroy()

    def _page(self, notebook, saving):
        grid = Gtk.Grid(column_spacing=10, row_spacing=12)
        grid.set_border_width(14)
        fields = {}
        paths = [("env", ".env の実ファイル", Gtk.FileChooserAction.OPEN),
                 ("auth", "Bot 専用 auth.json（任意）", Gtk.FileChooserAction.OPEN),
                 ("output", "新しい暗号化ファイル", Gtk.FileChooserAction.SAVE)] if saving else [
                     ("input", "暗号化バックアップ", Gtk.FileChooserAction.OPEN),
                     ("output", "新しい復元フォルダ（絶対パス）", None)]
        for row, (key, label, action) in enumerate(paths):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            entry = Gtk.Entry()
            entry.set_hexpand(True)
            fields[key] = entry
            grid.attach(entry, 1, row, 1, 1)
            if action is not None:
                button = Gtk.Button(label="選ぶ")
                button.connect("clicked", self._choose, entry, action)
                fields[key + "_choose"] = button
                grid.attach(button, 2, row, 1, 1)
        row = len(paths)
        for key, label in [("password", "復旧用パスワード")] + ([("confirm", "もう一度入力")] if saving else []):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            entry = Gtk.Entry()
            entry.set_visibility(False)
            entry.set_invisible_char("●")
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            entry.set_max_length(1024)
            fields[key] = entry
            self.passwords.append(entry)
            grid.attach(entry, 1, row, 2, 1)
            row += 1
        note = Gtk.Label(xalign=0)
        note.set_line_wrap(True)
        note.set_text("16文字以上の固有の長いパスフレーズを使用し、安全に控えてください。\n紛失すると復元できません。共有済みのテスト用パスワードは使わないでください。\n保存対象は .env と明示選択した専用 auth.json だけです。Bot を停止してから作成してください。" if saving else
                      "パスワードの入力は1回です。復元後は .env 内のパスと認証の有効性を確認してください。\n認証切れの場合は本人による再ログインが必要です。")
        grid.attach(note, 0, row, 3, 1)
        feedback = Gtk.Label(xalign=0)
        feedback.set_line_wrap(True)
        fields["feedback"] = feedback
        grid.attach(feedback, 0, row + 1, 3, 1)
        button = Gtk.Button(label="暗号化して保存" if saving else "復元する")
        button.connect("clicked", self._run, fields, saving)
        fields["button"] = button
        grid.attach(button, 0, row + 2, 3, 1)
        for key in ("password", "confirm") if saving else ("password",):
            fields[key].connect("changed", self._update_password_feedback, fields, saving)
        self._update_password_feedback(None, fields, saving)
        notebook.append_page(grid, Gtk.Label(label="バックアップ" if saving else "復元"))
        return fields

    def _update_password_feedback(self, _, fields, saving):
        valid, guidance = password_feedback(fields["password"].get_text(),
                                            fields["confirm"].get_text() if saving else None)
        fields["feedback"].set_text(guidance)
        fields["button"].set_sensitive(valid and not self.busy)

    def _run(self, _, fields, saving):
        if self.busy:
            return
        password = fields["password"].get_text()
        confirm = fields["confirm"].get_text() if saving else None
        valid, guidance = password_feedback(password, confirm)
        if not valid:
            self.status.set_text(guidance + " 入力内容はそのまま残しています。")
            password = confirm = None
            return
        path_keys = ("env", "output") if saving else ("input", "output")
        if any(not Path(fields[key].get_text()).is_absolute() for key in path_keys):
            self.status.set_text("ファイルと保存先には絶対パスを指定してください。入力内容はそのまま残しています。")
            password = confirm = None
            return
        if saving and fields["auth"].get_text() and not Path(fields["auth"].get_text()).is_absolute():
            self.status.set_text("Bot専用auth.jsonには絶対パスを指定してください。入力内容はそのまま残しています。")
            password = confirm = None
            return
        self.busy = True
        self.notebook.set_sensitive(False)
        try:
            if saving:
                auth = fields["auth"].get_text()
                durable = backup(fields["env"].get_text(), auth or None, fields["output"].get_text(), password)
                self.status.set_text("暗号化ファイルをローカルに保存しました。Library へのアップロードはまだ行っていません。")
            else:
                durable = restore(fields["input"].get_text(), fields["output"].get_text(), password)
                self.status.set_text("新しいフォルダに復元しました。設定パスとログイン状態の確認は別途必要です。")
            if not durable:
                self.status.set_text(self.status.get_text() + "\n注意: 出力は作成済みですが、ディスクへの確定保存を確認できませんでした。")
        except RecoveryError as error:
            messages = {
                "Wrong recovery passphrase or damaged backup. Nothing was restored.": "パスワードが違うか、バックアップが破損しています。復元は行われていません。",
                "Destination already exists. Choose a new name; existing data is never overwritten.": "保存先はすでに存在します。上書きせず、新しい保存先を選んでください。",
                "Use a recovery passphrase of 16 to 1024 characters.": "復旧用パスワードは16〜1024文字で入力してください。",
            }
            self.status.set_text("処理できませんでした: " + messages.get(str(error), str(error)))
        except Exception:
            self.status.set_text("処理できませんでした。ファイルの所有者・権限・空き容量と、保存先が未使用か確認してください。詳細ログは保存しません。")
        finally:
            password = None
            confirm = None
            for entry in self.passwords:
                entry.set_text("")
            self.busy = False
            self.notebook.set_sensitive(True)
            self._update_password_feedback(None, fields, saving)


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--dummy-ui"]):
        raise SystemExit("Usage: recovery_gui.py [--dummy-ui]. Password arguments are not accepted.")
    if not Gtk.init_check()[0]:
        raise SystemExit("Open this helper on a Linux desktop with GTK 3.")
    RecoveryWindow(dummy="--dummy-ui" in sys.argv)
    Gtk.main()
