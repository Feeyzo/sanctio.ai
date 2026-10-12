import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, Rectangle

plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Times New Roman", "Liberation Serif", "DejaVu Serif"]
fig, ax = plt.subplots(figsize=(11, 12))
ax.set_xlim(0, 110); ax.set_ylim(-5, 120); ax.axis("off")


def actor(x, y, name):
    ax.add_patch(plt.Circle((x, y + 4.2), 1.6, fill=False, lw=1.4))
    ax.plot([x, x], [y + 2.6, y - 1.5], "k", lw=1.4)
    ax.plot([x - 2.6, x + 2.6], [y + 1.4, y + 1.4], "k", lw=1.4)
    ax.plot([x, x - 2.2], [y - 1.5, y - 4.6], "k", lw=1.4)
    ax.plot([x, x + 2.2], [y - 1.5, y - 4.6], "k", lw=1.4)
    ax.text(x, y - 7, name, ha="center", va="top", fontsize=11, fontweight="bold")
    return (x, y)


ax.add_patch(Rectangle((22, -3), 66, 120, fill=False, lw=1.4))
ax.text(55, 114.5, "Secure AI Customer Service Agent API", ha="center", fontsize=13, fontweight="bold")

cases = {
    "obtain": (55, 107, "Obtain verified\ncustomer session"),
    "chat": (55, 98, "Send message\n(chat with agent)"),
    "track": (55, 89, "Track order"),
    "trouble": (55, 81, "Get guided\ntroubleshooting"),
    "cancel": (55, 72, "Cancel order"),
    "address": (55, 64, "Change delivery\naddress"),
    "refund": (55, 56, "Request refund"),
    "confirm": (55, 48, "Confirm / decline\naction"),
    "human": (55, 40, "Request human\nagent"),
    "login": (55, 32, "Admin login"),
    "dash": (55, 24, "View dashboard\n& statistics"),
    "handoff": (55, 16, "Manage handoffs\n& reply"),
    "approve": (55, 8.5, "Approve / reject\nhigh-risk action"),
    "security": (55, 1.5, "View security\nevents"),
}
for k, (x, y, t) in cases.items():
    ax.add_patch(Ellipse((x, y), 27, 6.6,
                         fill=True, fc="#f4f4f4", ec="black", lw=1.1))
    ax.text(x, y, t, ha="center", va="center", fontsize=9.5)

cust = actor(8, 78, "Customer")
biz = actor(8, 106, "Business\nSystem")
admin = actor(101, 18, "Support Agent /\nAdmin")
llm = actor(101, 84, "Gemini LLM")


def link(a, case, side):
    x, y, _ = cases[case]
    ex = x - 13.5 if side == "L" else x + 13.5
    if case in ("dash", "approve"):
        ex = x + 12.5
    if case in ("handoff", "security"):
        ex = x + 12.5
    ax.plot([a[0] + (3 if side == "L" else -3), ex], [a[1] + 1, y], "k", lw=0.8)


link(biz, "obtain", "L"); link(biz, "chat", "L")
for c in ["chat", "track", "trouble", "cancel", "address", "refund", "confirm", "human"]:
    link(cust, c, "L")
for c in ["login", "handoff", "security", "dash", "approve"]:
    x, y, _ = cases[c]
    ex = x + 13.5
    ax.plot([admin[0] - 3, ex], [admin[1] + 1, y], "k", lw=0.8)
for c in ["chat", "track", "trouble"]:
    x, y, _ = cases[c]
    ax.plot([llm[0] - 3, x + 13.5], [llm[1] + 1, y], "k--", lw=0.8)

plt.savefig("fig3_3_usecase.png", dpi=220, bbox_inches="tight", facecolor="white")
