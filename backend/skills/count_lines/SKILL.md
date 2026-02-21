---
name: count_lines
description: Count the number of lines in a given file
version: 1.0
---

# Count Lines Skill

This skill counts the number of lines in a specified file.

## Parameters
- `file_path`: The path to the file to count lines in (relative to project root)

## Steps

1. **Validate input**: Check that a file path was provided
2. **Check file exists**: Verify the file exists at the given path
3. **Count lines**: Use Python to count the number of lines in the file
4. **Return result**: Display the line count to the user

## Implementation

When invoked, the agent should:
1. Ask the user for the file path if not provided
2. Use the `read_file` tool to read the file content
3. Count the number of lines (split by newline)
4. Report the result

Example usage:
- User: "Count lines in myfile.txt"
- Agent: "The file 'myfile.txt' contains 42 lines."

## Notes
- Empty lines are counted as lines
- The file must be within the project directory for security reasons