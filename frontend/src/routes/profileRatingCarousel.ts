export type RatingSignalSlotPosition = "previous" | "active" | "next";
export type RatingSignalTrackPosition =
  | "farPrevious"
  | RatingSignalSlotPosition
  | "farNext";
export type RatingSignalCarouselDirection = -1 | 1;
export type RatingSignalPoseName =
  | RatingSignalTrackPosition
  | "exitPrevious"
  | "exitNext";

export interface RatingSignalSlot {
  position: RatingSignalSlotPosition;
  cardIndex: number;
}

export interface RatingSignalTrackItem {
  position: RatingSignalTrackPosition;
  cardIndex: number;
  virtualIndex: number;
}

export interface RatingSignalPose {
  "--signal-x": string;
  "--signal-scale": number;
  "--signal-rotation": string;
  autoAlpha: number;
  zIndex: number;
}

export const RATING_SIGNAL_POSES: Record<
  RatingSignalPoseName,
  RatingSignalPose
> = {
  farPrevious: {
    "--signal-x": "-178%",
    "--signal-scale": 0.66,
    "--signal-rotation": "-8deg",
    autoAlpha: 0,
    zIndex: 0,
  },
  previous: {
    "--signal-x": "-116%",
    "--signal-scale": 0.78,
    "--signal-rotation": "-4deg",
    autoAlpha: 0.5,
    zIndex: 1,
  },
  active: {
    "--signal-x": "-50%",
    "--signal-scale": 1,
    "--signal-rotation": "0deg",
    autoAlpha: 1,
    zIndex: 3,
  },
  next: {
    "--signal-x": "16%",
    "--signal-scale": 0.78,
    "--signal-rotation": "4deg",
    autoAlpha: 0.5,
    zIndex: 2,
  },
  farNext: {
    "--signal-x": "78%",
    "--signal-scale": 0.66,
    "--signal-rotation": "8deg",
    autoAlpha: 0,
    zIndex: 0,
  },
  exitPrevious: {
    "--signal-x": "-236%",
    "--signal-scale": 0.58,
    "--signal-rotation": "-11deg",
    autoAlpha: 0,
    zIndex: 0,
  },
  exitNext: {
    "--signal-x": "136%",
    "--signal-scale": 0.58,
    "--signal-rotation": "11deg",
    autoAlpha: 0,
    zIndex: 0,
  },
};

export interface RatingSignalMotionPlan {
  exiting: {
    position: "farPrevious" | "farNext";
    pose: "exitPrevious" | "exitNext";
  };
  movers: Array<{
    position: RatingSignalTrackPosition;
    pose: RatingSignalTrackPosition;
  }>;
}

export function getRatingSignalMotionPlan(
  direction: RatingSignalCarouselDirection,
): RatingSignalMotionPlan {
  if (direction === 1) {
    return {
      exiting: { position: "farPrevious", pose: "exitPrevious" },
      movers: [
        { position: "previous", pose: "farPrevious" },
        { position: "active", pose: "previous" },
        { position: "next", pose: "active" },
        { position: "farNext", pose: "next" },
      ],
    };
  }

  return {
    exiting: { position: "farNext", pose: "exitNext" },
    movers: [
      { position: "next", pose: "farNext" },
      { position: "active", pose: "next" },
      { position: "previous", pose: "active" },
      { position: "farPrevious", pose: "previous" },
    ],
  };
}

export function wrapRatingSignalIndex(index: number, count: number): number {
  if (count <= 0) return 0;
  return ((index % count) + count) % count;
}

export function getRatingSignalSlots(
  activeIndex: number,
  count: number,
): RatingSignalSlot[] {
  if (count <= 0) return [];

  const active = wrapRatingSignalIndex(activeIndex, count);
  if (count === 1) {
    return [{ position: "active", cardIndex: active }];
  }

  return [
    {
      position: "previous",
      cardIndex: wrapRatingSignalIndex(active - 1, count),
    },
    { position: "active", cardIndex: active },
    {
      position: "next",
      cardIndex: wrapRatingSignalIndex(active + 1, count),
    },
  ];
}

export function getRatingSignalTrack(
  activeStep: number,
  count: number,
): RatingSignalTrackItem[] {
  if (count <= 0) return [];
  if (count === 1) {
    return [
      {
        position: "active",
        cardIndex: 0,
        virtualIndex: activeStep,
      },
    ];
  }

  const positions: RatingSignalTrackPosition[] = [
    "farPrevious",
    "previous",
    "active",
    "next",
    "farNext",
  ];

  return positions.map((position, index) => {
    const virtualIndex = activeStep + index - 2;
    return {
      position,
      cardIndex: wrapRatingSignalIndex(virtualIndex, count),
      virtualIndex,
    };
  });
}
