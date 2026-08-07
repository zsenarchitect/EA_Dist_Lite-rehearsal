#!/usr/bin/python
# -*- coding: utf-8 -*-



__doc__ = """Check your EA coin balance and where you sit on the office leaderboard.

Quacks add up as you use EnneadTab tools, clear model warnings, and wait your
turn in the sync queue. The window shows your balance, your standing and your
recent transactions; nothing in the model changes."""
__title__ = "MiniBank"
__context__ = "zero-doc"
__tip__ = True

from pyrevit.forms import WPFWindow
# from pyrevit import forms #
from pyrevit import script #


import proDUCKtion # pyright: ignore
proDUCKtion.validify()
from EnneadTab import ERROR_HANDLE, SOUND, NOTIFICATION, LOG, ENVIRONMENT, LEADER_BOARD
from EnneadTab.REVIT import REVIT_APPLICATION

uidoc = REVIT_APPLICATION.get_uidoc()
doc = REVIT_APPLICATION.get_doc()
__persistentengine__ = True


# The balance lives in EnneadTab-Bank, not on this machine. Every number here is
# read from the service and nothing is ever written back from the client: the
# ledger is append-only and server-derived, so a desktop that could edit it would
# not be a bank. That is also why the old "Reset My User Data" and manual coin
# minting are gone -- they wrote to a local `money` key that no longer exists.


# A simple WPF form used to call the ExternalEvent
class MiniBank(WPFWindow):
    """
    Simple modeless form sample
    """

    def pre_actions(self):


        return


    @ERROR_HANDLE.try_catch_error()
    def __init__(self):
        self.pre_actions()

        xaml_file_name = "MiniBank.xaml" ###>>>>>> if change from window to dockpane, the top level <Window></Window> need to change to <Page></Page>
        WPFWindow.__init__(self, xaml_file_name)

        self.title_text.Text = "EnneadTab MiniBank"

        self.sub_text.Text = "The moment of truth... Let's see your balance!"


        self.Title = "EnneadTab MiniBank UI"

        self.set_image_source(self.logo_img, "{}\icon_logo_dark_background.png".format(ENVIRONMENT.IMAGE_FOLDER))
        self.set_image_source(self.duck_img, "happy_duck.png")
        self.manual_click = 0


        self.Show()
        # Cached read on open so the window appears instantly. "Refresh From Bank"
        # is the button that pays the network cost, and only when asked.
        self.display_summary(cached_only=True)


    @ERROR_HANDLE.try_catch_error()
    def display_summary(self, cached_only=True):
        """Balance + rank + season, or an honest explanation of why not."""
        wallet = LEADER_BOARD.get_wallet(cached_only=cached_only)
        board = LEADER_BOARD.get_leaderboard(cached_only=cached_only)

        balance = LEADER_BOARD.balance_from_wallet(wallet)
        rank = LEADER_BOARD.rank_from_leaderboard(board)

        if balance is None:
            # Never render a zero here. "No ledger rows yet" and "we could not
            # reach the bank" are different facts, and neither of them is
            # "you have 0 quacks".
            if not LEADER_BOARD.peek().get("signed_in"):
                self.sub_text.Text = ("Not signed in to enneadtab.com yet, so the "
                                      "bank cannot tell me your balance.")
            else:
                self.sub_text.Text = ("No transactions on your account yet. Use a "
                                      "few EnneadTab tools and check back.")
            self.debug_textbox.Text = "Pending events waiting to be sent: {}".format(
                LEADER_BOARD.peek().get("outbox_pending"))
            return

        line = "Balance: {} quacks".format(balance)
        if rank:
            line += "   |   Office rank: #{}".format(rank)
        season = (wallet or {}).get("season")
        if isinstance(season, dict) and season.get("name"):
            line += "   |   {}".format(season.get("name"))
        self.sub_text.Text = line

        lifetime = (wallet or {}).get("lifetimeEarned")
        detail = "Lifetime earned: {}".format(lifetime if lifetime is not None else "-")
        detail += "    Pending events: {}".format(
            LEADER_BOARD.peek().get("outbox_pending"))
        self.debug_textbox.Text = detail

    @ERROR_HANDLE.try_catch_error()
    def refresh_click(self, sender, e):
        """Hit the bank for real. Blocking, but the user asked for it."""
        self.sub_text.Text = "Asking the bank..."
        LEADER_BOARD.refresh()
        self.display_summary(cached_only=True)

    @ERROR_HANDLE.try_catch_error()
    def leaderboard_click(self, sender, e):
        """Print the anonymized office board.

        Everyone shows up as a Duck-XXXX handle -- the bank hashes identities
        server-side and never sends names or emails, so there is nothing here to
        de-anonymize even if we wanted to.
        """
        board = LEADER_BOARD.get_leaderboard(cached_only=True)
        output = script.get_output()
        if not isinstance(board, dict) or not board.get("hasBankData"):
            output.print_md("## Office Leaderboard\n\nNothing to show yet.")
            return

        own = board.get("self") or {}
        output.print_md("# Office Leaderboard")
        for row in board.get("top", []):
            if not isinstance(row, dict):
                continue
            marker = "  <-- you" if row.get("rank") == own.get("rank") else ""
            output.print_md("- **#{}**  {}  --  {} quacks{}".format(
                row.get("rank"), row.get("handle"), row.get("score"), marker))
        if own.get("rank"):
            output.print_md("\nYou are **#{}** as **{}**.".format(
                own.get("rank"), board.get("selfHandle")))

    @ERROR_HANDLE.try_catch_error()
    def check_account_click(self, sender, e):
        """Recent ledger entries -- what actually moved, and why."""
        wallet = LEADER_BOARD.get_wallet(cached_only=True)
        output = script.get_output()
        rows = (wallet or {}).get("recent")
        if not rows:
            output.print_md("## Transaction History\n\nNothing recorded yet.")
            return
        output.print_md("# Transaction History")
        for row in rows:
            if not isinstance(row, dict):
                continue
            output.print_md("- `{}`  **{:+d}**  {}".format(
                str(row.get("created_at", ""))[:19],
                int(row.get("delta", 0)),
                row.get("reason", "")))

    @ERROR_HANDLE.try_catch_error()
    def manual_coin_Click(self, sender, e):
        """Pure easter egg. It used to add real coins to a local file; now the
        ledger is server-side and this mints nothing -- it just quacks."""
        self.manual_click += 1

        # The toast used to read "+$1" / "+1UP". It mints nothing now, so saying
        # so would be a small lie printed next to a real balance.
        if self.manual_click % 10 == 0:
            NOTIFICATION.messenger(main_text = "1UP!\nNo quacks were harmed.")
            SOUND.play_sound("sound_effect_mario_1up.wav")
            return
        NOTIFICATION.messenger(main_text = "Quack!")
        SOUND.play_sound("sound_effect_mario_coin.wav")

    @ERROR_HANDLE.try_catch_error()
    def close_Click(self, sender, e):
        # This Raise() method launch a signal to Revit to tell him you want to do something in the API context
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        #print "mouse down"
        sender.DragMove()




@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    MiniBank()
################## main code below #####################
output = script.get_output()
output.close_others()


if __name__ == "__main__":
    main()
