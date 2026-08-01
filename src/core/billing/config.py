from dataclasses import dataclass


@dataclass
class BillingConfig:
    stripe_trial_days: int = 7
