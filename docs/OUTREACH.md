# 访谈招募：实际发出去的文字

The study's instruments are code; this one is a sentence somebody
reads on their phone. It belongs under version control for the same
reason the rest does — it is what was actually said, it will be
quoted in the methods section, and the IRB approved a description of
it rather than a vibe.

Everything here is Douyin 私信 (DM). The same text adapts for email
where a profile carries one.

---

## The constraint that shapes it

**On Douyin, the first message to a non-follower is usually the only
one that arrives.** Later messages queue behind a reply that may
never come. So the first message has to be complete enough to decide
on and short enough to read on a notification screen — and the full
consent information goes in the *second* message, after they answer.

That split is also the right research ethics: consent is informed by
the full description, and the full description is long. Nobody reads
a wall of text from a stranger.

---

## What the message must never say

**It does not tell anyone a particular post of theirs came down.**

Not "我看到你有条视频被下架了", not "我注意到你 10 月 3 日那条没有了".

Three reasons, in order of weight:

1. **It may be wrong.** Two of the three instrument faults found in
   the week of 10-08 produced *false* removals — on 10-09 to 10-13,
   about two thirds of one evidence type was the instrument, not the
   platform (METHODOLOGY 8b). Telling somebody their post was removed
   when it was a bug is not a correction you can make afterwards.
2. **It tells them they are being watched**, individually, by name,
   by a stranger. That is a different relationship from "I study this
   topic and would like to hear about your experience."
3. **It changes the answer.** A person told their post was removed
   will talk about that post. The interview is about what the
   experience is like, which is a larger thing.

If an interviewee raises a specific post themselves, that is theirs
to raise.

---

## Message 1 — the first DM

Short. Everything that matters for a yes/no, nothing else.

```
你好！我是美国 Wellesley College 的本科生【名字】，在做毕业论文，
研究中文平台上拉拉内容创作者的经历。

想请你聊 15 分钟：文字或语音都行，时间你定，有 50 元感谢费。
不会用到你的账号名、真名或任何截图。

我的个人主页：【链接】
有兴趣或者想先问清楚，回我一句就行，谢谢！
```

Why each line is there:

- **学校和身份在第一句。** A stranger asking about queer content
  needs to be placeable in the first line or the message reads as
  something else entirely.
- **"15 分钟" and "50 元" early.** They are the two facts that decide
  it. Burying compensation at the bottom reads as a catch.
- **"时间你定"** — the asymmetry is the whole problem with cold
  outreach; this is the cheapest thing that reduces it.
- **匿名 before the link**, because that is the fear.
- **The link does the credibility work** the message cannot. Without
  a page to point at, this is an anonymous stranger asking a queer
  creator to talk about censorship. **Do not start sending before the
  page is up.**
- **No mention of removal, takedown, 下架, or 审核.** See above.

---

## Message 2 — after they reply

Sent once they answer. This is the consent information.

```
太好了，谢谢你！说几句具体的，你看了觉得可以我们再约时间：

· 内容：聊聊你发这类内容的经历——平台上发东西的感受、有没有遇到
  过什么情况、后来有没有改变发东西的方式。没有标准答案，想到哪说
  到哪都行。
· 时长：15 分钟左右，你想多聊也可以。
· 形式：抖音私信文字、微信文字或语音，你方便哪种都行。
· 感谢费：50 元，微信或支付宝，聊完就发。中途不想聊了也照发。
· 匿名：不会出现你的真名、账号名、任何截图。引用的话会去掉能认出
  你的细节。录音只在你同意的情况下做，论文写完就删。
· 自愿：任何问题都可以跳过，随时可以停。

本研究已通过 Wellesley College 伦理审查委员会（IRB）审批，编号
【填写】。有任何问题都可以问我，或者发邮件到【邮箱】。

方便的话告诉我你哪天哪个时间段有空？
```

Note what is *not* promised: no confidentiality guarantee beyond what
a researcher can actually keep, and nothing about the platform
noticing. Do not add either.

---

## Message 3 — the questions

Not a script. Fifteen minutes of a semi-structured interview, in the
order that lets a person warm up:

1. 你一般都发什么样的内容？发多久了？
2. 发这些东西的时候，有没有想过「这条可能不太行」？是什么让你这么
   想的？
3. 有没有遇到过内容发不出去、或者发出去之后没了的情况？（**等她
   自己说**，不要替她断定）
4. 那次发生的时候，你知道是为什么吗？平台有没有说明？
5. 你当时做了什么？
6. 之后发东西的方式有变化吗？（标签、文案、画面、发布时间……）
7. 你身边发类似内容的人，会聊这些吗？
8. 还有什么是我没问到、但你觉得我应该知道的？

Question 3 is the hinge, and it is deliberately open. If she says no,
that is data: an account in the corpus that lost a post and did not
notice is a finding about how invisible this is.

---

## Where it is recorded

One command per message sent, so the queue never offers the same
person twice:

```bash
./.venv/bin/python -m app.outreach --mark <抖音号> sent
./.venv/bin/python -m app.outreach --mark <抖音号> replied --note "10-16 回了，周四晚"
./.venv/bin/python -m app.outreach --mark <抖音号> scheduled
./.venv/bin/python -m app.outreach --mark <抖音号> interviewed
./.venv/bin/python -m app.outreach --mark <抖音号> paid
./.venv/bin/python -m app.outreach --mark <抖音号> declined
```

`declined` and `no_reply` are permanent. On Douyin the one message
that gets through is spent; writing again to somebody who said no is
not a second attempt, it is a different act.

Progress, including how many of each cell have been approached:

```bash
./.venv/bin/python -m app.outreach --status
```

---

## The order to work in

From the 访谈名单 tab of `takedowns.html`, top down. It is not a
ranking — it is four cells (still down / came back × one post /
several) shuffled on a fixed seed and read round-robin, so stopping
at any point leaves the four roughly balanced (`app.outreach`).

**Take the next person in the order.** Use the tags column only to
notice when everybody who has said yes so far is posting about one
thing — and then say so in the methods section rather than
hand-picking to fix it.
