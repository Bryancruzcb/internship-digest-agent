import logging
import time

logger = logging.getLogger("StatefulAgent.Tools")

def search_news(topic: str) -> list:
    """Simulates a web search for the given topic."""
    logger.info(f"Tool Search: Searching for updates on topic '{topic}'...")
    time.sleep(1.5) # Simulate latency
    
    # Return mock results
    return [
        {
            "title": f"New breakthroughs in {topic} announced this week.",
            "source": "TechCrunch",
            "summary": f"Experts detail key enhancements and future growth sectors in the space of {topic}."
        },
        {
            "title": f"Why developers are migrating to modern {topic} architectures.",
            "source": "InfoQ",
            "summary": f"A comprehensive look at deployment pipelines and standard tools for developers working on {topic}."
        }
    ]

def compile_report(articles: list, analysis: str) -> str:
    """Formats the compiled articles and analysis into a markdown string."""
    logger.info("Tool Compiler: Formatting markdown report...")
    
    report = f"# Weekly Digest: Tech Reports\n\n"
    report += f"## Executive Summary\n{analysis}\n\n"
    report += f"## Collected Articles\n"
    
    for a in articles:
        report += f"- **{a['title']}** ({a['source']})\n  *{a['summary']}*\n"
        
    return report

def publish_report(report_content: str, filename: str = "weekly_report.md") -> str:
    """Writes the compiled report to disk."""
    logger.info(f"Tool Publisher: Writing report to {filename}...")
    import config
    output_path = config.BASE_DIR / filename
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    return str(output_path)
