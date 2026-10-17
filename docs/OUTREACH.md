# 访谈招募：批准过的文本，以及怎么用

**The wording below is not drafted here. It is Attachment 1 of
protocol #27037R, as approved.** This file exists to keep the
approved text where the rest of the instruments live, and to record
the operational choices around it.

A recruitment message is approved as a text. Rewriting it — even to
improve it — is a change to study materials, and a change to study
materials goes to the HRPP before it goes to a participant.

---

## The message

¥50 is offered in the first message, and the interview is 15–20
minutes. The two-stage design in the attachment that was uploaded
here — Version A with no compensation, Version B only if recruitment
proved insufficient — was **superseded by a later amendment**. That
file is an old draft; the text below is current.

```
你好！我叫杨依霖，在美国 Wellesley College 做研究，现在在做一个关于
中文拉拉相关短视频内容的项目。

我在做的研究是长期追踪一批公开发布的视频，看它们随着时间过去还在不在。
你的账号出现在我追踪的这批数据里，所以想来问问你有没有兴趣聊一聊。

我自己也是拉拉社群的一员，做这个研究一部分也是因为想把大家的经历
记录下来。

想聊的是：你在平台上发内容的经历、遇到过的审核情况，以及你自己决定
删掉某些内容时是怎么想的。大概 15 到 20 分钟，可以用腾讯会议、微信、
Zoom，或者就在这里打字聊，你选。

参与自愿。访谈结束后我会发一个 50 元红包作为对你时间的一点心意，
你也可以不要，不影响参与。你可以随时不回、中途退出，或者跳过任何
问题。我不会问也不会记录你的真名，写出来的时候会用化名。

如果有兴趣，或者想先了解更多，回复我就好。如果不方便，也完全没关系，
我不会再打扰你。

杨依霖
Wellesley College
yy106@wellesley.edu
```

### Three things in it worth not losing

- **It discloses how they were found.** "你的账号出现在我追踪的这批
  数据里" — selected on a sensitive attribute, said in the second
  line. This is the part of recruitment most easily got wrong, and
  it is already right.
- **It claims nothing about a specific post.** A set of videos is
  being tracked; it does not say "I saw yours come down" — which
  matters, because this instrument has been wrong about exactly
  that: between 10-09 and 10-13 about two thirds of one removal
  evidence was our fault rather than the platform's (METHODOLOGY
  8b). If an interviewee raises a particular post, that is theirs
  to raise.
- **It closes the door politely** — "如果不方便…我不会再打扰你" — and
  that is a promise to a person, which is why `declined` and
  `no_reply` are permanent in the record.

### One thing not to add

**No link to the personal page in the DM**, unless the HRPP has it.
The message, as approved and amended, ends at "回复我就好". The
account bio is the approved place for an address and it carries the
email.

## The account bio (also approved, Attachment 1)

Exactly this, in the Douyin profile:

```
杨依霖 | Wellesley College 研究项目账号

这是一个学术研究账号，用于一项关于中文短视频内容与平台审核的研究。
指导教授：Eni Mustafaraj（Wellesley College 计算机科学系）。
联系：yy106@wellesley.edu
```

This is the credibility anchor the protocol itself designed: a named
researcher, a named faculty supervisor, an institutional email. It
does the job a personal site was being built to do, and it is already
approved.

---

## After they reply: the consent script, not a second pitch

Attachment 2 is a **verbal consent script**, read (or typed) at the
start of the interview — not a second recruitment message. It covers
recording, pseudonyms, where data is stored, the PIPL cross-border
transfer notice, the right to withdraw, and three closing
confirmations:

1. 你已经满 18 岁了吗？
2. 上面说的这些，你有没有想问的？愿意参加吗？
3. 录音可以吗？不录也可以。

It is long because it has to be. Do not summarise it from memory in
the chat — read it from Attachment 2.

---

## Recording the contacts

```bash
./.venv/bin/python -m app.outreach --mark <抖音号> sent
./.venv/bin/python -m app.outreach --mark <抖音号> replied --note "10-17 回了"
./.venv/bin/python -m app.outreach --mark <抖音号> scheduled
./.venv/bin/python -m app.outreach --mark <抖音号> interviewed
./.venv/bin/python -m app.outreach --mark <抖音号> paid
./.venv/bin/python -m app.outreach --mark <抖音号> declined
./.venv/bin/python -m app.outreach --status
```

`declined` and `no_reply` are permanent, and the approved message
promises it: "如果不方便，也完全没关系，我不会再打扰你." That is a
commitment made to the person, not a workflow preference.

Anyone who arrives on their own — from the account bio, or a post —
is **outside the sampling frame** and must be marked so:

```bash
--note "自愿来的，不在抽样框内"
```

They can still be interviewed. They cannot be counted as part of the
stratified sample, because people who volunteer to talk about this
are not like people who were asked.

---

## The order to work in

From the 访谈名单 tab of `takedowns.html`, top down. Four cells
(still down / came back × one post / several), seeded shuffle, read
round-robin, so stopping at any point leaves the four roughly
balanced. **Take the next one. Do not pick.** The tags column is for
noticing when everybody who has said yes is posting about one thing —
and then saying so in the methods, not hand-picking to fix it.

---

## One line in the approval letter that says two things

The letter's subject, its title block and its **Review Type** field
all say *Expedited — Category 7, 45 CFR 46.110*. One sentence in the
body says the study *"meets the criteria for Exempt Human Subjects
Research under 45 CFR 46.104(d)"*.

Three places to one, and the one looks like template text left in.
So **Expedited, Category 7** is what the methods section should say.
It is still worth one line to hrpp@brandeis.edu to have it in
writing, since it is the sentence a committee would ask about — but
it is a footnote, not a blocker, and nothing waits on it.

The end-of-analysis date in the uploaded application (2026-10-20) is
also from the superseded draft; the amended protocol runs to around
March 2027.
