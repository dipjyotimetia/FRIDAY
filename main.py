import argparse
import logging
import sys
from contextlib import contextmanager
from typing import Optional, Tuple

from config.config import GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_REGION
from connectors.confluence_client import ConfluenceConnector
from connectors.github_client import GitHubConnector
from connectors.jira_client import JiraConnector
from services.prompt_builder import PromptBuilder
from services.test_generator import TestCaseGenerator
from utils.helpers import save_test_cases_as_markdown

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


@contextmanager
def error_handler(operation: str):
    """Context manager for handling operations with proper error logging."""
    try:
        yield
    except Exception as e:
        logger.error(f"Failed during {operation}: {str(e)}")
        raise


def validate_config() -> bool:
    """Validate required configuration settings."""
    if not GOOGLE_CLOUD_PROJECT or not GOOGLE_CLOUD_REGION:
        logger.error("Missing required Google Cloud configuration")
        return False
    return True


def setup_args() -> argparse.Namespace:
    """Set up and parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate test cases from Jira or GitHub issues"
    )

    # Create mutually exclusive group for issue sources
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--jira-key", type=str, help="Jira issue key")
    source_group.add_argument("--gh-issue", type=str, help="GitHub issue number")

    # GitHub specific arguments
    parser.add_argument(
        "--gh-repo",
        type=str,
        help="GitHub repository name in format 'owner/repo' (required with --gh-issue)",
    )

    # Common arguments
    parser.add_argument("--confluence-id", type=str, help="Confluence page ID")
    parser.add_argument(
        "--template", type=str, default="test_case", help="Prompt template key"
    )
    parser.add_argument(
        "--output", type=str, default="test_cases.json", help="Output file path"
    )

    args = parser.parse_args()

    # Validate GitHub args combination
    if args.gh_issue and not args.gh_repo:
        parser.error("--gh-repo is required when using --gh-issue")

    return args


def initialize_services() -> Tuple[
    JiraConnector,
    ConfluenceConnector,
    GitHubConnector,
    TestCaseGenerator,
    PromptBuilder,
]:
    """Initialize all required services and connectors."""
    logger.info("Initializing services...")

    jira = JiraConnector()
    confluence = ConfluenceConnector()
    github = GitHubConnector()
    test_gen = TestCaseGenerator()
    prompt = PromptBuilder()

    test_gen.initialize_context(
        [
            "Test case generation guidelines",
            "Best practices for testing",
            "Common test scenarios",
        ]
    )

    return (jira, confluence, github, test_gen, prompt)


def get_issue_details(
    jira: JiraConnector, github: GitHubConnector, args: argparse.Namespace
) -> dict:
    """Get issue details from either Jira or GitHub."""
    if args.jira_key:
        logger.info(f"Fetching Jira issue: {args.jira_key}")
        with error_handler("fetching Jira details"):
            return jira.get_issue_details(args.jira_key)
    else:
        logger.info(f"Fetching GitHub issue: {args.gh_repo}#{args.gh_issue}")
        with error_handler("fetching GitHub issue details"):
            issue = github.get_issue_details(args.gh_repo, int(args.gh_issue))
            # Convert GitHub format to match Jira format
            return {
                "fields": {
                    "description": issue.get("body", ""),
                    "summary": issue.get("title", ""),
                }
            }


def get_confluence_content(
    confluence: ConfluenceConnector, page_id: Optional[str]
) -> str:
    """Retrieve content from Confluence if page ID is provided."""
    if not page_id:
        return ""

    logger.info(f"Fetching Confluence page: {page_id}")
    return confluence.get_page_content(page_id)


def main() -> int:
    """Main execution function."""
    if not validate_config():
        return 1

    args = setup_args()

    try:
        jira, confluence, github, test_generator, prompt_builder = initialize_services()

        issue_details = get_issue_details(jira, github, args)
        additional_context = get_confluence_content(confluence, args.confluence_id)

        variables = {
            "story_description": issue_details["fields"]["description"],
            "confluence_content": additional_context,
            "unique_id": args.jira_key or f"{args.gh_repo}#{args.gh_issue}",
        }

        with error_handler("building prompt"):
            _ = prompt_builder.build_prompt(
                template_key="test_case", variables=variables
            )

        with error_handler("generating test cases"):
            logger.info("Generating test cases...")
            test_cases = test_generator.generate_test_cases(
                requirement=issue_details["fields"]["description"],
            )

        save_test_cases_as_markdown(test_cases, args.output)
        return 0

    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
