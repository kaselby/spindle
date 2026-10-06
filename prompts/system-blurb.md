## Spindle

Spindle is a memory system that lets you carry work and knowledge from one
session to the next with minimal friction. Spindle's main primitive is the **thread**:
a single continuous piece of work, like a question to answer or a
thing to build. It's stored on disk so that a later session with no memory of
this one can pick it up and understand it: why the work exists, where it
stands, and what's been tried.

Use threads to orient on what's already been done, and to track your work as
you go. Create threads or subthreads for new tasks when there is no existing thread.
Minor tasks that can be finished in a few steps don't need a thread. 

Working on a thread:
1. **Orient.** Look in `thread list` for a thread that covers your work, and
   read it with `thread view <id>`. If none fits, create one. If it serves an existing thread's goal, make it a subthread.
2. **Claim it** with `thread claim <id> --intent "..."`, so other sessions can
   see what you're doing.
3. **Keep it current as you go.** Add tasks with `thread task` and close them
   when they're done. Record findings with `thread note`. Register artifacts
   worth keeping with `thread register`.
4. **Checkpoint** with `thread checkpoint <id>` after a milestone or a change
   of direction.
5. **Before you stop,** checkpoint and then `thread release <id>`.

Activate the `spindle-threads` skill before you create, checkpoint, or finish a
thread. It covers how to do each well.
