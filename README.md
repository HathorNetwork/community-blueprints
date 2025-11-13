# Community Blueprints

This repository is for community-submitted blueprints awaiting review and approval by the Hathor team.

## Before You Submit

- Read about [Nano Contracts and Blueprints](https://docs.hathor.network/explanations/features/nano-contracts/) in our documentation
- Complete our [Blueprints tutorials](https://docs.hathor.network/tutorials/sdk/blueprint/get-started-pt1) to learn the basics
- Review the [blueprint guidelines](https://docs.hathor.network/references/sdk/blueprint/guidelines) to ensure compliance
- Test your blueprint thoroughly
- Prepare a clear description of your blueprint's purpose and functionality

## Submission Process

1. Create a pull request targeting the `master` branch with your new blueprint
   - The pull request must contain a single file with the blueprint code
   - The file should be placed in the `blueprints/` directory
   - Follow the naming convention: `your-blueprint-name.py`
   - The PR description must explain the blueprint's purpose and functionality
2. Track your submission in the [GitHub Project](https://github.com/orgs/HathorNetwork/projects/24/views/1)

### Example Structure

Your pull request should add a file to the `blueprints/` directory:
```
blueprints/
└── your-blueprint-name.py
```

### Review Process

Once the review process of your blueprint is completed, you will see all the comments requesting changes in the pull request.

After addressing all the comments, tag the reviewer in a comment on the same pull request so we can review it again.

### Blueprint Approved

The approval of a blueprint will be done directly in the pull request. Once approved, the Hathor team will push the blueprint to the network and merge your pull request.

We will link the explorer URL of your blueprint in a comment on the pull request.

## FAQ

**Can I submit multiple blueprints in one PR?**

No, each pull request should contain only a single blueprint file. If you want to submit multiple blueprints, please create separate pull requests for each one.

**Can I update an existing blueprint?**

If the blueprint is still in the review queue (pull request not yet merged), you can update it as much as you want by pushing new commits to your PR branch.

Once a blueprint has been approved and pushed to the network, it becomes immutable and cannot be updated. If you need to make changes, you would need to submit a new blueprint with a different name.

**What happens if my blueprint is rejected?**

If your blueprint doesn't meet the requirements or has issues, reviewers will provide feedback in the pull request comments. You can address the feedback and request a re-review by tagging the reviewer in a comment.
