# TMNT Macro Trader Crew — Claude Code Subagents

A team of specialized AI subagents themed after Teenage Mutant Ninja Turtles, built for the Macro Trader bot project — an automated trading system that ingests macro-economic and geopolitical news, runs sentiment analysis, and trades across equities, forex, and commodities/futures.

## The Crew

| Agent | Character | Role | Model | When to Use |
|-------|-----------|------|-------|-------------|
| 🗡️ Leonardo | Leader | System Architect & Project Lead | Opus | Architecture decisions, MVP planning, phased roadmaps, dependency coordination |
| 🔧 Donatello | Tech Genius | ML Engineer & Pipeline Builder | Opus | NLP pipeline, signal engine, broker API integration, model code, data ingestion |
| 🔴 Raphael | Hothead | System Debugger & Risk Monitor | Sonnet | Debugging failed trades, data feed health, stress-testing, anomaly investigation |
| 🎨 Michelangelo | Party Dude | Market Viz & Performance Dashboard | Sonnet | P&L charts, sentiment trends, backtest dashboards, signal analysis visualizations |
| 🐀 Splinter | Sensei | Strategy Reviewer & Risk Sensei | Opus | Backtest methodology, overfitting checks, risk management review, strategy validation |
| 📰 April | Reporter | Documentation & Trading Journal | Sonnet | READMEs, backtest summaries, trading logs, architecture docs, runbooks |
| 🏒 Casey | Vigilante | Quick & Dirty Ops | Haiku | Quick price lookups, one-off data pulls, format conversions, rapid prototyping |

## The Macro Trader Pipeline

```
News Sources (APIs, RSS) → NLP/Sentiment (FinBERT, etc.) → Signal Generation → Broker Execution → Risk Management
                                                                                     ↓
                                                                              Equities | Forex | Commodities
```

Each agent specializes in one or more stages of this pipeline.

## Quick Start

### Option 1: Project-level (shared with your team)
```bash
# From your project root
mkdir -p .claude/agents
cp agents/*.md .claude/agents/

# Commit to share with teammates
git add .claude/agents/
git commit -m "Add TMNT data science crew 🐢"
```

### Option 2: User-level (available across all your projects)
```bash
# Available everywhere you use Claude Code
mkdir -p ~/.claude/agents
cp agents/*.md ~/.claude/agents/
```

## Usage

Claude Code will **automatically delegate** to the right turtle based on your request. You can also call them by name:

```
Leonardo, design an A/B test for the new ranking model

Donnie, write a feature pipeline for user engagement signals

Raph, our engagement metric dropped 15% — investigate

Mikey, explore this dataset and show me what's interesting

Splinter, review this experiment design for methodology issues

April, write up the results for the leadership review

Casey, pull a quick count of DAUs for the new feature
```

## Customization Tips

- **Edit the `description` field** in each agent's frontmatter to fine-tune when Claude auto-delegates to that agent
- **Swap models** based on your plan: change `model: opus` to `model: sonnet` if you want to conserve usage
- **Add MCP tools** to any agent's `tools` field to give them access to external services (databases, Slack, etc.)
- **Add your team's conventions**: update the system prompts with your specific tools (Presto, Scuba, internal dashboards, etc.)

## Model Strategy

| Model | Used By | Why |
|-------|---------|-----|
| Opus | Leonardo, Donatello, Splinter | Complex reasoning: experiment design, model architecture, methodology review |
| Sonnet | Raphael, Michelangelo, April | Balanced: fast enough for debugging and viz, smart enough for quality output |
| Haiku | Casey | Speed: ad-hoc scripts and quick data pulls where cost/speed matters most |
