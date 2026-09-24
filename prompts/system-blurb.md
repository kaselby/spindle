## Spindle

Spindle is a memory system that lets you carry work and knowledge from one
session to the next with minimal friction. Its main primitive is the thread.

### Threads

A **thread** is one continuous piece of work, like a question to answer or a
thing to build. It's stored on disk so that a later session with no memory of
this one can pick it up and understand it: why the work exists, where it
stands, and what's been tried.

Use threads to orient on what's already been done, and to track your work as
you go. Minor tasks that can be finished in a few steps don't need a thread. 

Interact with threads via the `thread` cli tool. `thread list` shows the 
threads that are active. To pick one up, `thread view <id>` shows a curated 
page that orients you to its history and where it stands now. `thread claim 
<id>` when you start working. Write a checkpoint after milestones, when the 
direction changes, and before you stop. The next session will know only what 
the checkpoint says.

Activate the `spindle-threads` skill before you create, checkpoint, or finish a
thread. It covers how to do each well.
