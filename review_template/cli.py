import os
import sys
import click

# from review_template import acquire_pdfs
from review_template import backward_search
from review_template import cleanse_manual
from review_template import complete_manual
from review_template import data
from review_template import initialize
from review_template import process_duplicates_manual
from review_template import review_template
from review_template import sample_profile
from review_template import screen_1
from review_template import screen_2
from review_template import trace_entry
from review_template import trace_hash_id
from review_template import trace_search_result
from review_template import validate_major_changes
from review_template import validate_pdfs


class SpecialHelpOrder(click.Group):

    def __init__(self, *args, **kwargs):
        self.help_priorities = {}
        super(SpecialHelpOrder, self).__init__(*args, **kwargs)

    def get_help(self, ctx):
        self.list_commands = self.list_commands_for_help
        return super(SpecialHelpOrder, self).get_help(ctx)

    def list_commands_for_help(self, ctx):
        """reorder the list of commands when listing the help"""
        commands = super(SpecialHelpOrder, self).list_commands(ctx)
        return (c[1] for c in sorted(
            (self.help_priorities.get(command, 1), command)
            for command in commands))

    def command(self, *args, **kwargs):
        """Behaves the same as `click.Group.command()` except capture
        a priority for listing command names in help.
        """
        help_priority = kwargs.pop('help_priority', 1)
        help_priorities = self.help_priorities

        def decorator(f):
            cmd = super(SpecialHelpOrder, self).command(*args, **kwargs)(f)
            help_priorities[cmd.name] = help_priority
            return cmd

        return decorator


@click.group(cls=SpecialHelpOrder)
@click.pass_context
def main(ctx):
    """Review template pipeline
    
    Main commands: process | status"""


@main.command(help_priority=1)
@click.pass_context
def initialize(ctx):
    """Initialize repository"""
    initialize.initialize_repo()

@main.command(help_priority=2)
@click.pass_context
def process(ctx):
    """Process pipeline"""
    review_template.main()


@main.command(help_priority=3)
@click.pass_context
def status(ctx):
    """Show status"""
    os.system('pre-commit run -a')

@main.command(help_priority=4)
@click.pass_context
def complete_manual(ctx):
    """Complete records manually"""
    complete_manual.main()

@main.command(help_priority=5)
@click.pass_context
def cleanse_manual(ctx):
    """Cleanse records manually"""
    cleanse_manual.main()


@main.command(help_priority=6)
@click.pass_context
def proc_duplicates_manual(ctx):
    """Process duplicates manually"""
    process_duplicates_manual.main()


@main.command(help_priority=7)
@click.pass_context
def screen_1(ctx):
    """Execute screen 1"""
    screen_1.main()

@main.command(help_priority=8)
@click.pass_context
def screen_2(ctx):
    """Execute screen 2"""
    screen_2.main()

@main.command(help_priority=9)
@click.pass_context
def acquire_pdfs(ctx):
    """Acquire PDFs"""
    acquire_pdfs.main()


@main.command(help_priority=10)
@click.pass_context
def validate_pdfs(ctx):
    """Validate PDFs"""
    validate_pdfs.main()


@main.command(help_priority=11)
@click.pass_context
def backward_search(ctx):
    """Execute backward search based on PDFs"""
    backward_search.main()

@main.command(help_priority=12)
@click.pass_context
def data(ctx):
    """Execute data extraction"""
    data.main()

@main.command(help_priority=13)
@click.pass_context
def sample_profile(ctx):
    """Generate a sample profile"""
    sample_profile.main()

@main.command(help_priority=14)
@click.pass_context
def validate_major_changes(ctx):
    """Validate major changes (in prior versions)"""
    validate_major_changes.main()

@main.command(help_priority=15)
@click.pass_context
def trace_hash_id(ctx):
    """Trace a hash_id"""
    trace_hash_id.main()

@main.command(help_priority=16)
@click.pass_context
def trace_search_result(ctx):
    """Trace a search result"""
    trace_search_result.main()

@main.command(help_priority=16)
@click.pass_context
def trace_entry(ctx):
    """Trace an entry"""
    trace_entry.main()


if __name__ == '__main__':
    sys.exit(main())
