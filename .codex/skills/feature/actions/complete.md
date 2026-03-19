# Complete Action

1. Run a final review to ensure everything is complete
2. Confirm the feature status should move to `Completed`
3. Update `current-feature.md`:
   - set Status to `Completed`
   - make sure Goals and Notes reflect the finished implementation state
   - add a concise entry to `## History`
4. Reset `current-feature.md` for the next task as part of completion:
   - change Status back to `Not Started`
   - clear Goals and Notes
   - keep History intact
5. Commit the completed feature by default:
   - stage only the intended files
   - use a focused conventional commit message
   - verify before committing if not already done
6. Push the current branch to origin by default after the commit succeeds
7. Only merge as a separate explicit step if the user asks for it
